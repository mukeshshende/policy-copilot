"""
graph.py — LangGraph StateGraph definition for Policy Copilot
AIpportunity Pvt. Ltd.

Graph topology:

    START
      │
      ▼
  route_query          Decides which collections to search
      │
      ▼
   retrieve            Pulls TOP_K chunks per collection (audience-filtered)
      │
      ▼
 grade_documents       LLM scores each chunk: yes / no
      │
      ├─── (graded_docs empty) ──► handle_no_results ──► END
      │
      └─── (graded_docs non-empty) ──► generate ──► END

Compile once at module level with `build_graph()` and reuse the compiled
graph across requests — it is thread-safe after compilation.
"""

import logging
import os
import uuid
from typing import Any

from dotenv import load_dotenv
from langgraph.graph import StateGraph, START, END

load_dotenv()

from src.agent.state import AgentState, UserRole
from src.agent.nodes import (
    route_query,
    retrieve,
    grade_documents,
    generate,
    handle_no_results,
)

logger = logging.getLogger(__name__)


# ── Conditional edge function ──────────────────────────────────────────────────

def _route_after_grading(state: AgentState) -> str:
    """
    Branch after grade_documents:
      - "generate"         if at least one graded doc exists
      - "handle_no_results" if nothing passed the relevance filter
    """
    graded = state.get("graded_docs") or []
    if graded:
        return "generate"
    return "handle_no_results"


# ── Graph builder ──────────────────────────────────────────────────────────────

def build_graph() -> Any:
    """
    Construct, wire, and compile the Policy Copilot StateGraph.

    Returns a compiled LangGraph runnable.  Call `.invoke(state)` or
    `.stream(state)` on the returned object.
    """
    builder = StateGraph(AgentState)

    # Add nodes
    builder.add_node("route_query",       route_query)
    builder.add_node("retrieve",          retrieve)
    builder.add_node("grade_documents",   grade_documents)
    builder.add_node("generate",          generate)
    builder.add_node("handle_no_results", handle_no_results)

    # Linear edges
    builder.add_edge(START,            "route_query")
    builder.add_edge("route_query",    "retrieve")
    builder.add_edge("retrieve",       "grade_documents")

    # Conditional branch after grading
    builder.add_conditional_edges(
        "grade_documents",
        _route_after_grading,
        {
            "generate":          "generate",
            "handle_no_results": "handle_no_results",
        },
    )

    # Terminal edges
    builder.add_edge("generate",          END)
    builder.add_edge("handle_no_results", END)

    graph = builder.compile()
    logger.info("[build_graph] Policy Copilot graph compiled successfully.")
    return graph


# ── Langfuse callback factory ──────────────────────────────────────────────────

def _make_langfuse_handler(run_id: str, user_role: str, query: str) -> Any:
    """
    Build a LangfuseCallbackHandler for one graph run.

    Returns None (silently) if Langfuse env vars are not configured so the
    app still works without observability during local dev / CI.
    """
    public_key  = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
    secret_key  = os.environ.get("LANGFUSE_SECRET_KEY", "")
    host        = os.environ.get("LANGFUSE_HOST", "")

    if not (public_key and secret_key and host):
        logger.warning("[graph] Langfuse env vars not set — tracing disabled.")
        return None

    try:
        from langfuse.callback import CallbackHandler
        handler = CallbackHandler(
            public_key=public_key,
            secret_key=secret_key,
            host=host,
            trace_name="policy-copilot-query",
            session_id=run_id,
            metadata={
                "user_role": user_role,
                "query":     query,
            },
        )
        return handler
    except Exception as exc:
        logger.warning(f"[graph] Could not create Langfuse handler: {exc}")
        return None


# ── Convenience run functions ──────────────────────────────────────────────────

def run_query(
    query: str,
    user_role: UserRole,
    graph: Any = None,
) -> dict[str, Any]:
    """
    Run a single query through the Policy Copilot graph (no tracing).

    Args:
        query:     The user's question.
        user_role: One of: employee | manager | HR | IT_admin | Leadership
        graph:     Optional pre-compiled graph.  Built fresh if not provided.

    Returns:
        The final AgentState dict with `answer` and `sources` populated.
    """
    if graph is None:
        graph = build_graph()

    initial_state: AgentState = {
        "query":          query,
        "user_role":      user_role,
        "collections":    [],
        "retrieved_docs": [],
        "graded_docs":    [],
        "answer":         "",
        "sources":        [],
        "run_id":         str(uuid.uuid4()),
        "error":          "",
    }

    logger.info(
        f"[run_query] run_id={initial_state['run_id']} "
        f"role={user_role!r} query={query!r}"
    )

    final_state = graph.invoke(initial_state)
    return final_state


def run_query_traced(
    query: str,
    user_role: UserRole,
    graph: Any = None,
) -> dict[str, Any]:
    """
    Run a single query with Langfuse observability tracing.

    Identical to run_query() but attaches a LangfuseCallbackHandler so every
    LLM call (router, grader, generator) appears as a span in the Langfuse UI.

    Falls back to untraced execution if Langfuse env vars are missing.

    Args:
        query:     The user's question.
        user_role: One of: employee | manager | HR | IT_admin | Leadership
        graph:     Optional pre-compiled graph.  Built fresh if not provided.

    Returns:
        The final AgentState dict with `answer` and `sources` populated.
    """
    if graph is None:
        graph = build_graph()

    run_id = str(uuid.uuid4())

    initial_state: AgentState = {
        "query":          query,
        "user_role":      user_role,
        "collections":    [],
        "retrieved_docs": [],
        "graded_docs":    [],
        "answer":         "",
        "sources":        [],
        "run_id":         run_id,
        "error":          "",
    }

    handler = _make_langfuse_handler(run_id, user_role, query)
    config  = {"callbacks": [handler]} if handler else {}

    logger.info(
        f"[run_query_traced] run_id={run_id} "
        f"role={user_role!r} traced={handler is not None}"
    )

    final_state = graph.invoke(initial_state, config=config)
    return final_state


# ── Module-level compiled graph (import and reuse) ─────────────────────────────
# Importing modules can call build_graph() once:
#     from src.agent.graph import policy_graph
#     result = policy_graph.invoke(state)

policy_graph = build_graph()
