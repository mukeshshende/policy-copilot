"""
ingest.py — ChromaDB ingestion pipeline for Policy Copilot
AIpportunity Pvt. Ltd.

Reads .txt policy documents from data/policies/{hr,ops,it}/
Connects to Ollama embeddings on Windows host (192.168.1.16:11434)
Creates 3 ChromaDB collections with full metadata schema.

AUDIENCE METADATA DESIGN
─────────────────────────
ChromaDB metadata values must be scalar (str / int / float / bool).
Lists are not supported. Storing audience as a JSON string means the
Phase 2 where-filter `{"audience": {"$in": ["employee"]}}` would
compare the string '["HR","Leadership"]' against scalar values and
silently return zero results for everyone.

Fix: one boolean flag per role, pre-computed at ingest time.

    audience_employee:   True / False
    audience_manager:    True / False
    audience_HR:         True / False
    audience_IT_admin:   True / False
    audience_Leadership: True / False

Phase 2 query pattern (single key, no $or needed):
    where={f"audience_{state['user_role']}": True}

"all" in the raw audience list → all five flags set to True.
"""

import os
import glob
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from langchain_community.embeddings import OllamaEmbeddings
from langchain_community.document_loaders import TextLoader
from langchain_chroma import Chroma
from langchain.text_splitter import RecursiveCharacterTextSplitter

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ── Collection configuration ──────────────────────────────────────────────────

COLLECTION_CONFIG = {
    "hr_policies":  {"path": "hr",  "doc_type": "HR"},
    "ops_policies": {"path": "ops", "doc_type": "OPS"},
    "it_policies":  {"path": "it",  "doc_type": "IT"},
}

# ── Chunking parameters (locked — do not change without full re-ingestion) ────
CHUNK_SIZE = 300
CHUNK_OVERLAP = 50

# ── All valid role names (must match personas.py exactly) ─────────────────────
ALL_ROLES = ["employee", "manager", "HR", "IT_admin", "Leadership"]

# ── Raw audience token → role names it grants access to ──────────────────────
# "all"        → every role
# "IT"         → IT_admin (the raw policy header uses "IT"; the persona uses "IT_admin")
# "manager"    → manager only (does NOT imply employee access)
AUDIENCE_TOKEN_MAP: dict[str, list[str]] = {
    "all":        ALL_ROLES,
    "employee":   ["employee"],
    "manager":    ["manager"],
    "HR":         ["HR"],
    "IT":         ["IT_admin"],
    "IT_admin":   ["IT_admin"],
    "Leadership": ["Leadership"],
}


def parse_metadata_header(text: str) -> dict:
    """
    Parse the YAML-style metadata header block from a policy document.

    Expects the block to be the very first thing in the file:
        ---
        key: value
        ---
    Returns a dict of the parsed key/value pairs.
    """
    metadata: dict = {}
    lines = text.splitlines()
    in_header = False

    for line in lines:
        stripped = line.strip()
        if stripped == "---":
            if not in_header:
                in_header = True
                continue
            else:
                break  # second --- closes the header
        if in_header and ":" in stripped:
            key, _, value = stripped.partition(":")
            key = key.strip()
            value = value.strip()
            if key == "audience":
                if value.lower() == "all":
                    metadata["audience"] = ["all"]
                else:
                    metadata["audience"] = [v.strip() for v in value.split(",")]
            else:
                metadata[key] = value

    return metadata


def build_audience_flags(audience_list: list[str]) -> dict[str, bool]:
    """
    Convert the raw audience list from the document header into one boolean
    flag per role.  These flags are stored directly in ChromaDB metadata so
    Phase 2 can do a simple single-key equality filter:

        where={f"audience_{user_role}": True}

    Examples
    --------
    ["all"]               → all five flags True
    ["HR", "Leadership"]  → audience_HR=True, audience_Leadership=True, rest False
    ["IT", "manager"]     → audience_IT_admin=True, audience_manager=True, rest False
    """
    granted_roles: set[str] = set()
    for token in audience_list:
        granted_roles.update(AUDIENCE_TOKEN_MAP.get(token, [token]))

    return {f"audience_{role}": (role in granted_roles) for role in ALL_ROLES}


def build_chunk_metadata(
    doc_metadata: dict,
    doc_type: str,
    source_file: str,
    chunk_index: int,
) -> dict:
    """
    Build the metadata dict stored with each ChromaDB chunk.

    Locked key names for Phase 2 compatibility:
        doc_id, doc_type, sensitivity, version, ingested_at
        audience_employee, audience_manager, audience_HR,
        audience_IT_admin, audience_Leadership
        audience_raw  (comma-separated string — for human-readable audit only)
    """
    audience_list = doc_metadata.get("audience", ["all"])
    audience_flags = build_audience_flags(audience_list)

    meta = {
        "doc_id":       doc_metadata.get("doc_id", Path(source_file).stem),
        "doc_type":     doc_metadata.get("category", doc_type),
        "sensitivity":  doc_metadata.get("sensitivity", "internal"),
        "version":      doc_metadata.get("version", "1.0"),
        "title":        doc_metadata.get("title", ""),
        "ingested_at":  datetime.now(timezone.utc).isoformat(),
        "source_file":  source_file,
        "chunk_index":  chunk_index,
        # Human-readable audience string — NOT used for filtering
        "audience_raw": ", ".join(audience_list),
    }
    meta.update(audience_flags)
    return meta


def ingest_collection(
    collection_name: str,
    docs_path: str,
    chroma_persist_path: str,
    ollama_base_url: str,
    embed_model: str,
) -> dict:
    """
    Ingest all .txt files from docs_path into a named ChromaDB collection.

    Args:
        collection_name:     Name of the ChromaDB collection (e.g. "hr_policies")
        docs_path:           Absolute path to the folder containing .txt files
        chroma_persist_path: Absolute path for ChromaDB persistence directory
        ollama_base_url:     Ollama API base URL  e.g. "http://192.168.1.16:11434"
        embed_model:         Ollama embedding model e.g. "nomic-embed-text"

    Returns:
        {"collection": str, "doc_count": int, "chunk_count": int}
    """
    logger.info(f"{'='*60}")
    logger.info(f"Ingesting collection : {collection_name}")
    logger.info(f"  docs_path          : {docs_path}")
    logger.info(f"  chroma_persist_path: {chroma_persist_path}")
    logger.info(f"  ollama_base_url    : {ollama_base_url}")
    logger.info(f"  embed_model        : {embed_model}")

    if not os.path.isdir(docs_path):
        raise FileNotFoundError(f"docs_path does not exist: {docs_path}")

    txt_files = sorted(glob.glob(os.path.join(docs_path, "*.txt")))
    if not txt_files:
        raise ValueError(f"No .txt files found in: {docs_path}")

    logger.info(f"  Found {len(txt_files)} document(s)")

    # ── Ollama embeddings (calls Windows host) ────────────────────────────────
    embeddings = OllamaEmbeddings(
        model=embed_model,
        base_url=ollama_base_url,
    )

    # ── Text splitter ─────────────────────────────────────────────────────────
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        length_function=len,
    )

    # ── Load, split, annotate ─────────────────────────────────────────────────
    all_texts: list[str] = []
    all_metadatas: list[dict] = []
    all_ids: list[str] = []
    doc_type = COLLECTION_CONFIG.get(collection_name, {}).get("doc_type", collection_name)

    for file_path in txt_files:
        logger.info(f"  Processing: {os.path.basename(file_path)}")
        loader = TextLoader(file_path, encoding="utf-8")
        documents = loader.load()

        if not documents:
            logger.warning(f"    Empty document, skipping: {file_path}")
            continue

        raw_text = documents[0].page_content
        doc_metadata = parse_metadata_header(raw_text)
        chunks = splitter.split_text(raw_text)
        logger.info(f"    → {len(chunks)} chunk(s)  "
                    f"[sensitivity={doc_metadata.get('sensitivity','?')} "
                    f"audience_raw={doc_metadata.get('audience',[])}]")

        for i, chunk in enumerate(chunks):
            meta = build_chunk_metadata(
                doc_metadata=doc_metadata,
                doc_type=doc_type,
                source_file=os.path.basename(file_path),
                chunk_index=i,
            )
            chunk_id = f"{meta['doc_id']}_chunk_{i:04d}"
            all_texts.append(chunk)
            all_metadatas.append(meta)
            all_ids.append(chunk_id)

    total_chunks = len(all_texts)
    logger.info(f"  Total chunks prepared: {total_chunks}")

    # ── Write to ChromaDB ─────────────────────────────────────────────────────
    os.makedirs(chroma_persist_path, exist_ok=True)

    vector_store = Chroma(
        collection_name=collection_name,
        embedding_function=embeddings,
        persist_directory=chroma_persist_path,
    )

    # Clear before re-ingesting to avoid duplicate chunks on repeated runs
    existing = vector_store.get()
    if existing and existing.get("ids"):
        logger.info(f"  Clearing {len(existing['ids'])} existing chunk(s)…")
        vector_store.delete(ids=existing["ids"])

    # Embed and store in batches of 50 (avoids Ollama request timeouts)
    batch_size = 50
    for start in range(0, total_chunks, batch_size):
        end = min(start + batch_size, total_chunks)
        logger.info(f"  Embedding batch [{start}:{end}]…")
        vector_store.add_texts(
            texts=all_texts[start:end],
            metadatas=all_metadatas[start:end],
            ids=all_ids[start:end],
        )

    final_count = len(vector_store.get()["ids"])
    logger.info(f"  ✓ {collection_name}: {len(txt_files)} docs, {final_count} chunks stored")

    return {
        "collection": collection_name,
        "doc_count":  len(txt_files),
        "chunk_count": final_count,
    }


def run_ingestion(
    base_policies_path: Optional[str] = None,
    chroma_persist_path: Optional[str] = None,
    ollama_base_url: Optional[str] = None,
    embed_model: Optional[str] = None,
) -> dict:
    """
    Run ingestion for all three collections.  Parameters default to .env values.

    Returns:
        {"hr_policies": {...}, "ops_policies": {...}, "it_policies": {...}}
    """
    base_policies = base_policies_path or os.path.join(
        os.path.dirname(__file__), "..", "..", "data", "policies"
    )
    chroma_dir = chroma_persist_path or os.environ.get(
        "CHROMA_PERSIST_DIR", "./data/chroma_db"
    )
    ollama_url = ollama_base_url or os.environ.get(
        "OLLAMA_BASE_URL", "http://192.168.1.16:11434"
    )
    model = embed_model or os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text")

    results: dict = {}
    total_chunks = 0

    for collection_name, config in COLLECTION_CONFIG.items():
        docs_path = os.path.join(base_policies, config["path"])
        result = ingest_collection(
            collection_name=collection_name,
            docs_path=docs_path,
            chroma_persist_path=chroma_dir,
            ollama_base_url=ollama_url,
            embed_model=model,
        )
        results[collection_name] = result
        total_chunks += result["chunk_count"]

    logger.info("=" * 60)
    logger.info("INGESTION SUMMARY")
    for coll, res in results.items():
        logger.info(f"  {coll:<22} docs={res['doc_count']:>2}  chunks={res['chunk_count']:>3}")
    logger.info(f"  {'TOTAL':<22} chunks={total_chunks:>3}")
    logger.info("=" * 60)

    if not (100 <= total_chunks <= 250):
        logger.warning(
            f"Total chunk count {total_chunks} is outside expected range [100, 250]. "
            "Check document word counts and splitter config."
        )

    return results


def _test_audience_flags() -> None:
    cases = [
        (["all"],              {"employee": True,  "manager": True,  "HR": True,  "IT_admin": True,  "Leadership": True}),
        (["HR", "Leadership"], {"employee": False, "manager": False, "HR": True,  "IT_admin": False, "Leadership": True}),
        (["IT", "manager"],    {"employee": False, "manager": True,  "HR": False, "IT_admin": True,  "Leadership": False}),
        (["Leadership"],       {"employee": False, "manager": False, "HR": False, "IT_admin": False, "Leadership": True}),
    ]
    all_passed = True
    for audience_list, expected in cases:
        flags = build_audience_flags(audience_list)
        for role, expected_val in expected.items():
            actual = flags[f"audience_{role}"]
            if actual != expected_val:
                print(f"FAIL  audience={audience_list}  role={role}  expected={expected_val}  got={actual}")
                all_passed = False
    if all_passed:
        print("All audience flag tests PASSED")


if __name__ == "__main__":
    import sys
    if "--test-flags" in sys.argv:
        _test_audience_flags()
    else:
        results = run_ingestion()
        print(json.dumps(results, indent=2))
