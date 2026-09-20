"""One-off: migrate backend/.env to LLM_* keys without printing secrets."""
from pathlib import Path
import re

p = Path(__file__).resolve().parent.parent / ".env"
text = p.read_text(encoding="utf-8")

def grab(name: str) -> str:
    m = re.search(rf"^{name}\s*=\s*(.*)$", text, re.M)
    if not m:
        return ""
    return m.group(1).strip().strip('"').strip("'")

key = grab("LLM_API_KEY") or grab("GROQ_API_KEY")
models = grab("LLM_MODELS")
if not models:
    primary = grab("GROQ_MODEL_PRIMARY") or "openai/gpt-oss-120b"
    fallback = grab("GROQ_MODEL_FALLBACK") or "qwen/qwen3.8-27b"
    models = f"{primary},{fallback}" if fallback and fallback != primary else primary

base = grab("LLM_BASE_URL") or grab("GROQ_BASE_URL") or "https://api.groq.com/openai/v1"

new = "\n".join(
    [
        f"LLM_API_KEY={key}",
        f"LLM_BASE_URL={base}",
        f"LLM_MODELS={models}",
        "DATA_DIR=./data",
        "SQLITE_PATH=./data/app.db",
        "CORS_ORIGINS=http://localhost:3000",
        "QUERY_ROW_LIMIT=500",
        "QUERY_TIMEOUT_SECONDS=30",
        "",
    ]
)
p.write_text(new, encoding="utf-8")
print("migrated ok; models=", models)
print("key present=", bool(key))
