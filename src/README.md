# src — Policy Copilot Source Code

This directory contains all Python source code for the Policy Copilot agent.

---

## Structure

```
src/
├── agent/
│   ├── state.py       # AgentState TypedDict — shared data structure for all nodes
│   ├── nodes.py       # LangGraph node functions (route, check_access, retrieve, grade, generate)
│   ├── graph.py       # StateGraph wiring, run_query(), run_query_traced()
│   └── prompts.py     # ChatPromptTemplate definitions (router, grader, generator)
├── governance/
│   └── governance.py  # GovernanceDB — SQLite logging for every agent run
├── ingestion/
│   └── ingest.py      # One-time ChromaDB ingestion pipeline
└── app.py             # Gradio UI entry point
```

---

## Agent (`src/agent/`)

### state.py

Defines `AgentState` — the single TypedDict that flows through every LangGraph node. Key fields:

| Field | Type | Purpose |
|---|---|---|
| `query` | str | User's question (immutable) |
| `user_role` | UserRole | One of: employee, manager, HR, IT_admin, Leadership |
| `collections` | list | Collections to search — set by route_query |
| `retrieved_docs` | list[Document] | Raw chunks from ChromaDB (accumulates) |
| `graded_docs` | list[Document] | Chunks that passed the relevance grader |
| `answer` | str | Final generated answer |
| `sources` | list[str] | Unique source filenames from graded chunks |
| `access_denied` | bool | Set True by check_access when role is not authorised |
| `llm_model` | str | Model override for Demo Mode (empty = use env default) |
| `run_id` | str | UUID for governance log correlation |

### nodes.py

Seven node functions — each takes `AgentState` and returns a partial dict:

| Node | What it does |
|---|---|
| `route_query` | LLM classifies query → hr / ops / it (or all three) |
| `check_access` | Unfiltered top-1 search — denies if best match is restricted for this role |
| `handle_access_denied` | Returns clear denial message with contact emails |
| `retrieve` | ChromaDB similarity search with `audience_{role}=True` filter |
| `grade_documents` | LLM scores each chunk yes/no; fallback if all rejected |
| `generate` | LLM synthesises final answer from graded chunks |
| `handle_no_results` | Returns polite fallback when zero chunks retrieved |

### graph.py

Wires nodes into a `StateGraph` and exposes two runner functions:

- `run_query(query, user_role, graph)` — plain run, no tracing
- `run_query_traced(query, user_role, graph, llm_model)` — attaches `LangfuseCallbackHandler`

### prompts.py

Three `ChatPromptTemplate` objects:

- `ROUTER_PROMPT` — outputs `hr`, `ops`, `it` or a combination
- `GRADER_PROMPT` — outputs `yes` or `no` per chunk
- `GENERATOR_PROMPT` — grounded answer generation with role context

---

## Governance (`src/governance/`)

### governance.py

`GovernanceDB` wraps a SQLite database (`data/governance.db`) opened in WAL mode for concurrent-safe writes. Every agent run is logged with: `run_id`, `query`, `user_role`, `answer`, `sources`, `timestamp`.

---

## Ingestion (`src/ingestion/`)

### ingest.py

Run once (or after adding new policy documents) to chunk and embed all files in `data/policies/` into ChromaDB. Each chunk gets five boolean audience flags (`audience_employee`, `audience_manager`, etc.) and a `sensitivity` field set from the document header.

```bash
cd ~/policy-copilot
source .venv/bin/activate
python -m src.ingestion.ingest
```

---

## App (`src/app.py`)

Gradio UI with a role dropdown and an LLM model selector (Demo Mode). Calls `run_query_traced()` on every submit and logs the result to GovernanceDB.

### Screenshot

![Gradio UI](../docs/screenshots/ui-answer.png)

---

## Running Locally

```bash
python -m src.app
# Open http://localhost:7860
```

Requires `.env` with `OLLAMA_BASE_URL`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`.
