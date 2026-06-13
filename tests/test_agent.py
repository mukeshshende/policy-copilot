"""
test_agent.py — End-to-end test harness for Policy Copilot
AIpportunity Pvt. Ltd.

Runs every persona's queries through the compiled graph and logs results
to the governance DB.  Prints a summary table at the end.

Usage
──────
    cd ~/policy-copilot
    source .venv/bin/activate
    python -m tests.test_agent                    # all personas, all queries
    python -m tests.test_agent --role employee    # single role
    python -m tests.test_agent --quick            # first query per persona only

Pass/Fail criteria
───────────────────
  PASS  — outcome is "answered" and answer length > 50 chars
  SKIP  — outcome is "no_results" (not a failure — just no matching docs)
  FAIL  — outcome is "error" OR answer length <= 50 chars
"""

import argparse
import logging
import sys
import os

# Ensure project root is on the path when run as `python -m tests.test_agent`
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.WARNING,          # suppress node-level INFO during tests
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

from src.agent.graph import build_graph
from src.governance.governance import GovernanceDB
from tests.personas import PERSONAS, Persona


# ── Result record ──────────────────────────────────────────────────────────────

def _run_one(
    query: str,
    persona: Persona,
    graph,
    db: GovernanceDB,
) -> dict:
    """Run a single query and return a result summary dict."""
    import uuid
    from src.agent.state import AgentState

    initial_state: AgentState = {
        "query":          query,
        "user_role":      persona["role"],
        "collections":    [],
        "retrieved_docs": [],
        "graded_docs":    [],
        "answer":         "",
        "sources":        [],
        "run_id":         str(uuid.uuid4()),
        "error":          "",
    }

    try:
        final = graph.invoke(initial_state)
        db.log_run(final)

        error_msg  = final.get("error", "") or ""
        graded     = final.get("graded_docs") or []
        answer     = final.get("answer", "") or ""

        if error_msg:
            outcome = "error"
        elif not graded:
            outcome = "no_results"
        else:
            outcome = "answered"

        verdict = (
            "FAIL" if outcome == "error" or (outcome == "answered" and len(answer) <= 50)
            else "SKIP" if outcome == "no_results"
            else "PASS"
        )

        return {
            "persona":    persona["name"],
            "role":       persona["role"],
            "query":      query,
            "outcome":    outcome,
            "verdict":    verdict,
            "answer_len": len(answer),
            "sources":    final.get("sources") or [],
            "error":      error_msg,
        }

    except Exception as exc:
        logger.exception(f"Unhandled exception for query={query!r}")
        return {
            "persona":    persona["name"],
            "role":       persona["role"],
            "query":      query,
            "outcome":    "error",
            "verdict":    "FAIL",
            "answer_len": 0,
            "sources":    [],
            "error":      str(exc),
        }


# ── Pretty printer ─────────────────────────────────────────────────────────────

def _print_result(r: dict, idx: int) -> None:
    verdict_display = {
        "PASS": "✓ PASS",
        "FAIL": "✗ FAIL",
        "SKIP": "~ SKIP",
    }.get(r["verdict"], r["verdict"])

    print(f"\n[{idx}] {verdict_display}  role={r['role']}  persona={r['persona']}")
    print(f"     Q: {r['query']}")
    print(f"     outcome={r['outcome']}  answer_len={r['answer_len']}")
    if r["sources"]:
        print(f"     sources: {', '.join(r['sources'])}")
    if r["error"]:
        print(f"     ERROR: {r['error']}")


def _print_summary(results: list[dict]) -> None:
    total  = len(results)
    passed = sum(1 for r in results if r["verdict"] == "PASS")
    skipped = sum(1 for r in results if r["verdict"] == "SKIP")
    failed = sum(1 for r in results if r["verdict"] == "FAIL")

    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    print(f"  Total  : {total}")
    print(f"  PASS   : {passed}")
    print(f"  SKIP   : {skipped}  (no_results — not a failure)")
    print(f"  FAIL   : {failed}")
    print("=" * 60)

    if failed > 0:
        print("\nFailed queries:")
        for r in results:
            if r["verdict"] == "FAIL":
                print(f"  [{r['role']}] {r['query']}")
                if r["error"]:
                    print(f"    → {r['error']}")
    print()


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Policy Copilot test harness")
    parser.add_argument(
        "--role",
        choices=["employee", "manager", "HR", "IT_admin", "Leadership"],
        help="Run tests for a single role only",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Run only the first query per persona",
    )
    args = parser.parse_args()

    # Filter personas
    personas = PERSONAS
    if args.role:
        personas = [p for p in PERSONAS if p["role"] == args.role]
        if not personas:
            print(f"No persona found for role={args.role!r}")
            sys.exit(1)

    print("=" * 60)
    print("Policy Copilot — Test Harness")
    print(f"Personas : {len(personas)}")
    print(f"Mode     : {'quick (1 query/persona)' if args.quick else 'full (3 queries/persona)'}")
    print("=" * 60)

    print("\nCompiling graph …")
    graph = build_graph()
    print("Graph compiled.\n")

    db      = GovernanceDB()
    results = []
    idx     = 1

    for persona in personas:
        queries = persona["queries"][:1] if args.quick else persona["queries"]
        for query in queries:
            print(f"Running [{idx}] {persona['role']} / {persona['name']} …", end=" ", flush=True)
            result = _run_one(query, persona, graph, db)
            results.append(result)
            print(result["verdict"])
            _print_result(result, idx)
            idx += 1

    _print_summary(results)

    # Print governance DB stats
    stats = db.stats()
    print("Governance DB stats (all-time):")
    for k, v in stats.items():
        print(f"  {k:<20} {v}")
    print()

    db.close()

    # Exit with non-zero code if any FAIL
    failed = sum(1 for r in results if r["verdict"] == "FAIL")
    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
