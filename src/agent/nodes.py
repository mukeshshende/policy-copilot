"""
nodes.py — LangGraph node functions for Policy Copilot
AIpportunity Pvt. Ltd.

Node execution order (defined in graph.py):
    route_query → retrieve → grade_documents → generate
                                             ↘ handle_no_results  (if 0 graded docs)

Each node receives the full AgentState and returns a partial dict that
LangGraph merges back into the state.
"""

import logging
import os
from typing import Any

from dotenv import load_dotenv
from langchain_community.chat_models import ChatOllama
from langchain_community.embeddings import OllamaEmbeddings
from langchain_chroma import Chroma
from langchain_core.documents import Document

from src.agent.state import AgentState, CollectionName
from src.agent.prompts import ROUTER_PROMPT, GRADER_PROMPT, GENERATOR_PROMPT

load_dotenv()

logger = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────────────────
OLLAMA_BASE_URL  = os.environ.get("OLLAMA_BASE_URL",    "http://192.168.1.16:11434")
OLLAMA_LLM_MODEL = os.environ.get("OLLAMA_LLM_MODEL",   "qwen2.5:7b")
OLLAMA_EMBED_MODEL = os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text")
CHROMA_PERSIST_DIR = os.environ.get("CHROMA_PERSIST_DIR",  "./data/chroma_db")

# Number of chunks to retrieve per collection
TOP_K = 5

# All valid collection names
ALL_COLLECTIONS: list[CollectionName] = ["hr_policies", "ops_policies", "it_policies"]

# Router token → collection name mapping
ROUTER_TOKEN_MAP: dict[str, CollectionName] = {
    "hr":  "hr_policies",
    "ops": "ops_policies",
    "it":  "it_policies",
}


def _get_llm() -> ChatOllama:
    """Return a ChatOllama instance pointing at the Windows Ollama host."""
    return ChatOllama(
        model=OLLAMA_LLM_MODEL,
        base_url=OLLAMA_BASE_URL,
        temperature=0,
    )


def _get_embeddings() -> OllamaEmbeddings:
    """Return OllamaEmbeddings pointing at the Windows Ollama host."""
    return OllamaEmbeddings(
        model=OLLAMA_EMBED_MODEL,
        base_url=OLLAMA_BASE_URL,
    )


# ── Node 1: route_query ────────────────────────────────────────────────────────

def route_query(state: AgentState) -> dict[str, Any]:
    """
    Determine which ChromaDB collections to search for the given query.

    Calls the LLM with ROUTER_PROMPT.  Parses the comma-separated output
    into a list of CollectionName values.  Falls back to all three collections
    if parsing fails.

    Returns:
        {"collections": [CollectionName, ...]}
    """
    logger.info(f"[route_query] query={state['query']!r}")

    chain = ROUTER_PROMPT | _get_llm()
    response = chain.invoke({"query": state["query"]})
    raw_output = response.content.strip().lower()
    logger.info(f"[route_query] LLM output: {raw_output!r}")

    collections: list[CollectionName] = []
    for token in raw_output.replace(" ", "").split(","):
        token = token.strip()
        if token in ROUTER_TOKEN_MAP:
            collections.append(ROUTER_TOKEN_MAP[token])

    if not collections:
        logger.warning(
            f"[route_query] Could not parse router output {raw_output!r}. "
            "Defaulting to all collections."
        )
        collections = list(ALL_COLLECTIONS)

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[CollectionName] = []
    for c in collections:
        if c not in seen:
            seen.add(c)
            unique.append(c)

    logger.info(f"[route_query] → collections={unique}")
    return {"collections": unique}


# ── Node 2: retrieve ───────────────────────────────────────────────────────────

def retrieve(state: AgentState) -> dict[str, Any]:
    """
    Search each routed ChromaDB collection with the audience filter applied.

    Filter pattern:   where={f"audience_{user_role}": True}
    This ensures a user only sees chunks their role is permitted to access.

    Returns:
        {"retrieved_docs": [Document, ...]}   (accumulates via operator.add)
    """
    query     = state["query"]
    user_role = state["user_role"]
    collections = state.get("collections") or list(ALL_COLLECTIONS)

    logger.info(
        f"[retrieve] query={query!r} role={user_role!r} "
        f"collections={collections}"
    )

    embeddings   = _get_embeddings()
    audience_key = f"audience_{user_role}"
    all_docs: list[Document] = []

    for collection_name in collections:
        logger.info(f"[retrieve]   searching {collection_name} …")
        vector_store = Chroma(
            collection_name=collection_name,
            embedding_function=embeddings,
            persist_directory=CHROMA_PERSIST_DIR,
        )
        docs = vector_store.similarity_search(
            query=query,
            k=TOP_K,
            filter={audience_key: True},
        )
        logger.info(f"[retrieve]   {collection_name} → {len(docs)} doc(s)")
        all_docs.extend(docs)

    logger.info(f"[retrieve] total retrieved: {len(all_docs)}")
    return {"retrieved_docs": all_docs}


# ── Node 3: grade_documents ────────────────────────────────────────────────────

def grade_documents(state: AgentState) -> dict[str, Any]:
    """
    Score each retrieved chunk for relevance to the query.

    Calls GRADER_PROMPT for every chunk.  Only chunks that receive a "yes"
    response are kept.  Returns an empty list if nothing passes — the graph's
    conditional edge will route to handle_no_results in that case.

    Returns:
        {"graded_docs": [Document, ...]}
    """
    query         = state["query"]
    retrieved     = state.get("retrieved_docs") or []

    logger.info(f"[grade_documents] grading {len(retrieved)} chunk(s) …")

    llm   = _get_llm()
    chain = GRADER_PROMPT | llm

    graded: list[Document] = []
    for doc in retrieved:
        response = chain.invoke({
            "query":    query,
            "document": doc.page_content,
        })
        verdict = response.content.strip().lower()
        relevant = verdict.startswith("yes")
        logger.info(
            f"[grade_documents]   source={doc.metadata.get('source_file','?')!r} "
            f"chunk={doc.metadata.get('chunk_index','?')} → {verdict!r}"
        )
        if relevant:
            graded.append(doc)

    logger.info(f"[grade_documents] kept {len(graded)} / {len(retrieved)}")
    return {"graded_docs": graded}


# ── Node 4: generate ───────────────────────────────────────────────────────────

def generate(state: AgentState) -> dict[str, Any]:
    """
    Generate a grounded answer from the graded document chunks.

    Builds a context string from graded_docs, calls GENERATOR_PROMPT, and
    extracts unique source file names for citation.

    Returns:
        {"answer": str, "sources": [str, ...]}
    """
    query      = state["query"]
    user_role  = state["user_role"]
    graded     = state.get("graded_docs") or []

    # Build context block
    context_parts: list[str] = []
    for doc in graded:
        source = doc.metadata.get("source_file", "unknown")
        context_parts.append(f"[Source: {source}]\n{doc.page_content}")
    context = "\n\n---\n\n".join(context_parts)

    logger.info(
        f"[generate] query={query!r} role={user_role!r} "
        f"context_chunks={len(graded)}"
    )

    llm   = _get_llm()
    chain = GENERATOR_PROMPT | llm
    response = chain.invoke({
        "query":     query,
        "context":   context,
        "user_role": user_role,
    })

    answer = response.content.strip()

    # Deduplicated sources list
    seen_sources: set[str] = set()
    sources: list[str] = []
    for doc in graded:
        src = doc.metadata.get("source_file", "unknown")
        if src not in seen_sources:
            seen_sources.add(src)
            sources.append(src)

    logger.info(f"[generate] answer_len={len(answer)}  sources={sources}")
    return {"answer": answer, "sources": sources}


# ── Node 5: handle_no_results ──────────────────────────────────────────────────

def handle_no_results(state: AgentState) -> dict[str, Any]:
    """
    Fallback node reached when grade_documents returns zero relevant chunks.

    Returns a polite, honest answer instead of an empty or hallucinated response.

    Returns:
        {"answer": str, "sources": []}
    """
    logger.info(
        f"[handle_no_results] no relevant docs for query={state['query']!r} "
        f"role={state['user_role']!r}"
    )
    answer = (
        "I could not find relevant policy information to answer your question. "
        "This may be because:\n"
        "• The topic is not covered in the current policy documents, or\n"
        "• Your role does not have access to the relevant policy.\n\n"
        "Please contact HR (hr@aiopportunity.in) or IT (it-support@aiopportunity.in) "
        "for further assistance."
    )
    return {"answer": answer, "sources": []}
