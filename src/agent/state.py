"""
state.py — AgentState definition for Policy Copilot
AIpportunity Pvt. Ltd.

Every LangGraph node reads from and writes to this TypedDict.
The graph passes this dict through the node chain; nodes return
partial dicts that LangGraph merges via the reducer functions.

FIELD GUIDE
───────────
query           Raw question from the user (immutable across the run).
user_role       One of: employee | manager | HR | IT_admin | Leadership
                Used as the ChromaDB audience filter key:
                    where={f"audience_{user_role}": True}
collections     Which ChromaDB collections to search.
                Determined by the router node based on query keywords.
retrieved_docs  Raw LangChain Document objects returned by the retriever.
graded_docs     Subset of retrieved_docs that passed the relevance grader.
answer          Final generated answer string.
sources         List of unique source_file values from graded_docs metadata.
run_id          UUID assigned at graph entry — used to correlate governance log.
error           Non-empty string if any node hits an unrecoverable error.
"""

from __future__ import annotations

import operator
from typing import Annotated, Literal
from typing_extensions import TypedDict

from langchain_core.documents import Document

# ── Valid role literals ────────────────────────────────────────────────────────
UserRole = Literal["employee", "manager", "HR", "IT_admin", "Leadership"]

# ── Valid collection names ─────────────────────────────────────────────────────
CollectionName = Literal["hr_policies", "ops_policies", "it_policies"]


class AgentState(TypedDict):
    """
    Shared state threaded through every node in the Policy Copilot graph.

    LangGraph merges node return dicts into this state automatically.
    Fields that accumulate across nodes use operator.add as reducer;
    scalar fields are last-write-wins.
    """

    # ── Inputs (set at graph entry, never mutated) ─────────────────────────────
    query: str
    user_role: UserRole

    # ── Router output ──────────────────────────────────────────────────────────
    # Which collections to search. Router may set 1, 2, or all 3.
    collections: list[CollectionName]

    # ── Retriever output ───────────────────────────────────────────────────────
    # Annotated with operator.add so multiple retrieve calls accumulate docs.
    retrieved_docs: Annotated[list[Document], operator.add]

    # ── Grader output ──────────────────────────────────────────────────────────
    graded_docs: list[Document]

    # ── Generator output ───────────────────────────────────────────────────────
    answer: str
    sources: list[str]

    # ── LLM model override (Demo Mode) ────────────────────────────────────────
    # Empty string = use OLLAMA_LLM_MODEL from env (default behaviour).
    # Set to a model name (e.g. "gemma4:31b") to override for this run only.
    llm_model: str

    # ── Governance / observability ─────────────────────────────────────────────
    run_id: str          # UUID for governance log correlation
    error: str           # empty string = no error; non-empty = node failed
