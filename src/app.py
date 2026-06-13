"""
app.py — Gradio UI for Policy Copilot
AIpportunity Pvt. Ltd.

Launch:
    cd ~/policy-copilot
    source .venv/bin/activate
    python -m src.app

Then open: http://192.168.1.32:7860
"""

import logging
import os

from dotenv import load_dotenv
load_dotenv()

import gradio as gr

from src.agent.graph import build_graph, run_query_traced
from src.governance.governance import GovernanceDB

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ── Compile graph and open DB once at startup ──────────────────────────────────
logger.info("Compiling Policy Copilot graph …")
_graph = build_graph()
logger.info("Graph ready.")

_db = GovernanceDB()

# ── Role options (must match ALL_ROLES in ingest.py) ──────────────────────────
ROLES = ["employee", "manager", "HR", "IT_admin", "Leadership"]


# ── Core handler ───────────────────────────────────────────────────────────────

def ask_policy(question: str, role: str) -> tuple[str, str]:
    """
    Gradio handler — called on every Submit click.

    Returns:
        (answer_text, sources_text)  — two strings for two Gradio outputs
    """
    question = question.strip()
    if not question:
        return "Please enter a question.", ""
    if not role:
        return "Please select your role.", ""

    logger.info(f"[app] role={role!r} question={question!r}")

    try:
        final = run_query_traced(query=question, user_role=role, graph=_graph)
        _db.log_run(final)

        answer  = final.get("answer", "").strip()
        sources = final.get("sources") or []

        if not answer:
            answer = "No answer was generated. Please try rephrasing your question."

        sources_text = (
            "\n".join(f"• {s}" for s in sources)
            if sources else "No sources cited."
        )
        return answer, sources_text

    except Exception as exc:
        logger.exception("[app] Unhandled error")
        return f"An error occurred: {exc}", ""


# ── Gradio UI ──────────────────────────────────────────────────────────────────

def build_ui() -> gr.Blocks:
    with gr.Blocks(
        title="Policy Copilot — AIpportunity Pvt. Ltd.",
        theme=gr.themes.Soft(),
    ) as demo:

        gr.Markdown(
            """
            # 🏢 Policy Copilot
            **AIpportunity Pvt. Ltd.** — HR · OPS · IT Policy Assistant

            Ask any question about company policies. Answers are filtered to
            your role — you will only see policies you are authorised to access.
            """
        )

        with gr.Row():
            with gr.Column(scale=3):
                question_box = gr.Textbox(
                    label="Your Question",
                    placeholder="e.g. How many days of annual leave am I entitled to?",
                    lines=3,
                )
            with gr.Column(scale=1):
                role_dropdown = gr.Dropdown(
                    choices=ROLES,
                    value="employee",
                    label="Your Role",
                )

        submit_btn = gr.Button("Ask Policy Copilot", variant="primary")

        with gr.Row():
            answer_box = gr.Textbox(
                label="Answer",
                lines=10,
                interactive=False,
            )

        sources_box = gr.Textbox(
            label="Sources",
            lines=3,
            interactive=False,
        )

        # Example questions
        gr.Examples(
            examples=[
                ["How many days of annual leave am I entitled to?",        "employee"],
                ["What is the work from home policy?",                     "employee"],
                ["What is the travel expense reimbursement process?",      "manager"],
                ["What are the document retention requirements?",          "manager"],
                ["What is the disciplinary action procedure?",             "HR"],
                ["What is the acceptable use policy for company devices?", "IT_admin"],
                ["What is the company's business continuity plan?",        "Leadership"],
            ],
            inputs=[question_box, role_dropdown],
            label="Example Questions",
        )

        submit_btn.click(
            fn=ask_policy,
            inputs=[question_box, role_dropdown],
            outputs=[answer_box, sources_box],
        )

        # Allow Enter key to submit
        question_box.submit(
            fn=ask_policy,
            inputs=[question_box, role_dropdown],
            outputs=[answer_box, sources_box],
        )

        gr.Markdown(
            """
            ---
            *Powered by LangGraph · ChromaDB · Ollama (qwen2.5:7b) · Langfuse*
            """
        )

    return demo


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    host = "0.0.0.0"
    port = int(os.environ.get("GRADIO_PORT", 7860))

    logger.info(f"Starting Gradio on {host}:{port} …")
    ui = build_ui()
    ui.launch(
        server_name=host,
        server_port=port,
        share=False,
    )
