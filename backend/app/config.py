from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Always resolve .env relative to backend/, not the process cwd
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_ENV_FILE = _BACKEND_DIR / ".env"


class Settings(BaseSettings):
    """OpenAI-compatible LLM settings — model IDs come only from env (no hardcoding)."""

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Model-agnostic (preferred)
    llm_api_key: str = ""
    llm_base_url: str = "https://openrouter.ai/api/v1"
    # Comma-separated model IDs tried in order
    llm_models: str = "openrouter/free"
    # Groq (or other) fallback when primary provider rate-limits
    llm_fallback_api_key: str = ""
    llm_fallback_base_url: str = "https://api.groq.com/openai/v1"
    llm_fallback_models: str = "openai/gpt-oss-120b,qwen/qwen3.8-27b"
    # Must stay under provider OTPM (Groq free Qwen tier enforces ~1000)
    llm_max_tokens: int = 800
    # Tighter cap for simple factual Q&A — keep enough room for reasoning models
    llm_max_tokens_simple: int = 800
    # Optional comma-separated faster models for simple intents (tried first)
    llm_models_fast: str = ""
    # Keep only the last N messages (plus system) when calling the LLM
    llm_max_history: int = 16
    # Soft cap on tool-result JSON chars fed back into the model
    llm_tool_result_chars: int = 2000
    # Soft cap on checkpointed history kept for simple turns
    llm_max_history_simple: int = 8

    # Backward-compatible names
    groq_api_key: str = ""
    groq_base_url: str = ""
    groq_model_primary: str = ""
    groq_model_fallback: str = ""

    data_dir: Path = Path("./data")
    sqlite_path: Path = Path("./data/app.db")
    cors_origins: str = "http://localhost:3000"

    query_row_limit: int = 40
    query_timeout_seconds: int = 30
    # Rows shown back to the LLM (subset of query_row_limit)
    llm_preview_rows: int = 15

    @field_validator(
        "llm_api_key",
        "llm_fallback_api_key",
        "groq_api_key",
        "llm_models",
        "llm_models_fast",
        "llm_fallback_models",
        "groq_model_primary",
        "groq_model_fallback",
        "llm_base_url",
        "llm_fallback_base_url",
        "groq_base_url",
        mode="before",
    )
    @classmethod
    def _strip_quotes(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip().strip('"').strip("'")
        return v

    @property
    def api_key(self) -> str:
        return (self.llm_api_key or self.groq_api_key).strip()

    @property
    def base_url(self) -> str:
        return (
            self.llm_base_url
            or self.groq_base_url
            or "https://api.groq.com/openai/v1"
        ).rstrip("/")

    @property
    def model_chain(self) -> list[str]:
        """Ordered unique model IDs from env."""
        parts: list[str] = []
        if self.llm_models.strip():
            parts.extend(self.llm_models.split(","))
        else:
            if self.groq_model_primary.strip():
                parts.append(self.groq_model_primary)
            if self.groq_model_fallback.strip():
                parts.extend(self.groq_model_fallback.split(","))

        seen: set[str] = set()
        out: list[str] = []
        for p in parts:
            name = p.strip().strip('"').strip("'")
            if name and name not in seen:
                seen.add(name)
                out.append(name)
        return out

    @property
    def model_chain_fast(self) -> list[str]:
        """Faster models for simple intents; falls back to model_chain."""
        parts: list[str] = []
        if self.llm_models_fast.strip():
            parts.extend(self.llm_models_fast.split(","))
        seen: set[str] = set()
        out: list[str] = []
        for p in parts:
            name = p.strip().strip('"').strip("'")
            if name and name not in seen:
                seen.add(name)
                out.append(name)
        return out or self.model_chain

    @property
    def fallback_model_chain(self) -> list[str]:
        parts: list[str] = []
        if self.llm_fallback_models.strip():
            parts.extend(self.llm_fallback_models.split(","))
        seen: set[str] = set()
        out: list[str] = []
        for p in parts:
            name = p.strip().strip('"').strip("'")
            if name and name not in seen:
                seen.add(name)
                out.append(name)
        return out

    @property
    def fallback_api_key(self) -> str:
        return self.llm_fallback_api_key.strip()

    @property
    def fallback_base_url(self) -> str:
        return (
            self.llm_fallback_base_url.strip() or "https://api.groq.com/openai/v1"
        ).rstrip("/")

    def llm_candidates(self, primary_models: list[str]) -> list[tuple[str, str, str]]:
        """Primary provider models first; then Groq (or configured fallback)
        when LLM_FALLBACK_API_KEY is set.
        """
        out: list[tuple[str, str, str]] = []
        primary_key = self.api_key
        primary_url = self.base_url
        if primary_key:
            for model in primary_models:
                out.append((primary_key, primary_url, model))

        fb_key = self.fallback_api_key
        if fb_key:
            fb_url = self.fallback_base_url
            fb_models = self.fallback_model_chain or [
                "openai/gpt-oss-120b",
                "qwen/qwen3.8-27b",
            ]
            for model in fb_models:
                out.append((fb_key, fb_url, model))
        return out

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    data_dir = settings.data_dir
    if not data_dir.is_absolute():
        data_dir = (_BACKEND_DIR / data_dir).resolve()
    sqlite_path = settings.sqlite_path
    if not sqlite_path.is_absolute():
        sqlite_path = (_BACKEND_DIR / sqlite_path).resolve()
    object.__setattr__(settings, "data_dir", data_dir)
    object.__setattr__(settings, "sqlite_path", sqlite_path)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    return settings


def reload_settings() -> Settings:
    get_settings.cache_clear()
    try:
        from app.agent import graph as agent_graph

        agent_graph._make_llm.cache_clear()
    except Exception:
        pass
    return get_settings()
