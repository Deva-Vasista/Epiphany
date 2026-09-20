# Approach write-up — Epiphany

## Approach

Scoped to the four acceptance criteria: multi-file upload, cross-file analysis, visual insights, and deliberate “delta” engineering on top of raw LLM capability. The agent never runs arbitrary code. It has three tools — `query_data` (DuckDB SQL), `forecast` (statsmodels), `render_chart` (Vega-Lite) — each with server-side validation. Schema profiling runs on upload so the model sees ground-truth table/column names before the first token.

Stack: FastAPI + LangGraph (checkpointed sessions) + DuckDB + SQLite on the backend; Next.js + Vega-Lite on the frontend. Inference via Groq open-weight models (`openai/gpt-oss-120b`, Qwen3 on 429), interpreting the brief’s “open-source AI models” as open-weight models served through an API — flagged here in case the panel intends local-only weights.

## Key decisions

1. **Profile before reason** — dtypes, null %, cardinality, samples are stored and injected into every turn.
2. **SQL-first, not code-exec** — DuckDB joins/aggs across files; SQL is parsed and restricted to a single SELECT against whitelisted session tables.
3. **Forecast math stays in Python** — date parse failure, frequency inference, and insufficient seasonal history return structured errors or a low-confidence linear fallback — never a silent fake.
4. **Chart encodings are validated** — LLM proposes mark + channels; dtype mismatch falls back to rule-based defaults; specs embed inline `data.values`.
5. **Dashboards are snapshots** — one SQLite row fetch, no recompute. Trade-off: they do not live-sync if source files change (acceptable for Q&A, not live BI).

## What I’d build next

- Sandboxed arbitrary code (E2B) for analysis SQL cannot express  
- Time-series foundation models (e.g. TimesFM) for heterogeneous short series  
- Live dashboards that re-run the source query on open  
- Auth / multi-user / long-term cross-session memory  
