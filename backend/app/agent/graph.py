"""LangGraph agent with Groq tool-calling and SSE event emission."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any, AsyncIterator, Literal, Optional, Sequence, TypedDict
from uuid import uuid4

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel, Field
from typing_extensions import Annotated

from app.agent.prompts import SYSTEM_PROMPT
from app.config import get_settings
from app.services.upload import schema_catalog_for_session
from app.tools.forecast import forecast as forecast_impl
from app.tools.query_data import query_data as query_data_impl
from app.tools.render_chart import render_chart as render_chart_impl


Intent = Literal["simple", "viz", "forecast"]


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    session_id: str


class QueryDataArgs(BaseModel):
    sql: str = Field(..., description="A single read-only SELECT statement, DuckDB dialect.")
    reasoning: str = Field(..., description="One sentence: why this query answers the question.")


class ForecastPoint(BaseModel):
    date: str
    value: float


class ForecastArgs(BaseModel):
    series: list[ForecastPoint]
    horizon: int = Field(..., ge=1, le=60)


class ChartEncoding(BaseModel):
    x: str
    y: str
    color: Optional[str] = None


class RenderChartArgs(BaseModel):
    data: list[dict[str, Any]]
    mark: Literal["bar", "line", "point", "area"]
    encoding: ChartEncoding
    title: str
    auto_save: bool = Field(
        default=False,
        description=(
            "True when the user asked for a dashboard/overview/multiple visualizations; "
            "False for a single ad hoc chart."
        ),
    )


_VIZ_RE = re.compile(
    r"\b("
    r"dashboard|overview|visuali[sz]e|visuali[sz]ation|chart|charts|plot|plots|"
    r"graph|graphs|heatmap|histogram|key\s+metrics|build\s+a\s+board|multiple\s+charts"
    r")\b",
    re.I,
)
_FORECAST_RE = re.compile(
    r"\b("
    r"fore?\s*casts?|forcasts?|predict(?:ion|ions|ing)?|projection|projections|"
    r"next\s+\d*\s*(?:month|months|quarter|quarters|year|years)|"
    r"upcoming\s+(?:month|quarter|year)|future"
    r")\b",
    re.I,
)


def classify_intent(question: str) -> Intent:
    """Route simple factual Qs to a leaner tool/prompt path."""
    q = (question or "").strip()
    if _FORECAST_RE.search(q):
        return "forecast"
    if _VIZ_RE.search(q):
        return "viz"
    return "simple"


def _build_tools(session_id: str, *, intent: Intent = "simple") -> list[StructuredTool]:
    def query_data(sql: str, reasoning: str) -> str:
        result = query_data_impl(session_id, sql, reasoning)
        settings = get_settings()
        if isinstance(result, dict) and "rows" in result:
            rows = result["rows"] or []
            n = settings.llm_preview_rows
            result = {
                **result,
                "rows": rows[:n],
                "truncated": result.get("truncated") or len(rows) > n,
                "row_count": result.get("row_count", len(rows)),
            }
        return json.dumps(result, default=str)

    def forecast(series: list[Any], horizon: int) -> str:
        normalized = []
        for point in series[:200]:
            if hasattr(point, "model_dump"):
                normalized.append(point.model_dump())
            elif isinstance(point, dict):
                normalized.append(point)
            else:
                normalized.append({"date": str(point), "value": 0.0})
        result = forecast_impl(normalized, horizon)
        if isinstance(result, dict) and "history" in result:
            hist = result.get("history") or []
            result = {**result, "history": hist[-24:]}
        return json.dumps(result, default=str)

    def render_chart(
        data: list[dict[str, Any]],
        mark: str,
        encoding: Any,
        title: str,
        auto_save: bool = False,
    ) -> str:
        enc = encoding.model_dump() if hasattr(encoding, "model_dump") else dict(encoding)
        capped = data[:200] if isinstance(data, list) else data
        result = render_chart_impl(capped, mark, enc, title)
        result["auto_save"] = bool(auto_save)
        return json.dumps(result, default=str)

    tools: list[StructuredTool] = [
        StructuredTool.from_function(
            func=query_data,
            name="query_data",
            description=(
                "Execute a single read-only SQL SELECT against the uploaded dataset(s), "
                "registered as DuckDB tables for this session. Use for all aggregation, "
                "filtering, cross-file joins, and trend extraction."
            ),
            args_schema=QueryDataArgs,
        ),
        StructuredTool.from_function(
            func=render_chart,
            name="render_chart",
            description=(
                "Render a chart from query/forecast rows. Pick the mark that fits the data: "
                "bar (rankings/categories), line (time trends), area (volume over time), "
                "point (scatter/correlation). Set encodings (x/y/color) to match the question. "
                "Use even when the user did not say 'chart' if a visual clarifies the answer. "
                "Set auto_save=true for dashboard/overview/multi-viz requests; false for a "
                "single ad hoc chart."
            ),
            args_schema=RenderChartArgs,
        ),
    ]

    if intent in ("viz", "forecast"):
        tools.append(
            StructuredTool.from_function(
                func=forecast,
                name="forecast",
                description=(
                "Forecast future values of a univariate time series. Call ONCE after a single "
                "query_data that already aggregated the series. Pass [{date, value}, ...] and "
                "horizon (periods ahead, 1–60). Do not call query_data again for the same series."
            ),
                args_schema=ForecastArgs,
            )
        )
    return tools


@lru_cache(maxsize=32)
def _make_llm(model: str, max_tokens: int, api_key: str, base_url: str) -> ChatOpenAI:
    if not api_key:
        raise RuntimeError(
            "LLM_API_KEY (or LLM_FALLBACK_API_KEY) is not set in backend/.env"
        )
    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=0.1,
        max_tokens=max_tokens,
    )


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 20] + "\n…[truncated]"


def _compact_tool_payload(tool: str, parsed: Any) -> Any:
    """Shrink tool outputs before they re-enter the LLM context."""
    settings = get_settings()
    preview_n = settings.llm_preview_rows
    if not isinstance(parsed, dict):
        return parsed
    if tool == "query_data":
        rows = parsed.get("rows") or []
        return {
            "error": parsed.get("error"),
            "message": parsed.get("message"),
            "sql": parsed.get("sql"),
            "reasoning": parsed.get("reasoning"),
            "row_count": parsed.get("row_count", len(rows)),
            "truncated": parsed.get("truncated") or len(rows) > preview_n,
            "rows": rows[:preview_n],
        }
    if tool == "forecast":
        return {
            "error": parsed.get("error"),
            "reason": parsed.get("reason"),
            "confidence": parsed.get("confidence"),
            "frequency": parsed.get("frequency"),
            "method": parsed.get("method"),
            "note": parsed.get("note"),
            "horizon": parsed.get("horizon"),
            "forecast": (parsed.get("forecast") or [])[:12],
            "history_tail": (parsed.get("history") or [])[-8:],
        }
    if tool == "render_chart":
        return {
            "error": parsed.get("error"),
            "title": parsed.get("title"),
            "mark": parsed.get("mark"),
            "encoding": parsed.get("encoding"),
            "corrected": parsed.get("corrected"),
            "independent_y": parsed.get("independent_y"),
            "auto_save": parsed.get("auto_save", False),
            "dashboard_id": parsed.get("dashboard_id"),
            "has_spec": "vega_lite_spec" in parsed,
            "note": "Chart rendered for the user UI; do not re-emit the full Vega spec.",
        }
    return parsed


def _messages_for_llm(
    messages: Sequence[BaseMessage],
    *,
    max_hist: Optional[int] = None,
) -> list[BaseMessage]:
    """Trim history and compact tool payloads to cut tokens per turn.

    Always keeps the latest HumanMessage so model chat templates (e.g. Qwen)
    still see a user query after long tool loops.
    """
    settings = get_settings()
    limit = settings.llm_tool_result_chars
    hist_cap = max_hist if max_hist is not None else settings.llm_max_history

    system_msgs = [m for m in messages if isinstance(m, SystemMessage)]
    other = [m for m in messages if not isinstance(m, SystemMessage)]

    last_human: Optional[HumanMessage] = None
    for m in reversed(other):
        if isinstance(m, HumanMessage):
            last_human = m
            break

    if len(other) > hist_cap:
        tail = other[-hist_cap:]
        if last_human is not None and not any(isinstance(m, HumanMessage) for m in tail):
            # User turn fell outside the window — pin it at the front of the tail
            tail = [last_human] + other[-(hist_cap - 1) :]
        other = tail

    out: list[BaseMessage] = []
    if system_msgs:
        out.append(system_msgs[0])

    for msg in other:
        if isinstance(msg, ToolMessage):
            try:
                parsed = json.loads(msg.content) if isinstance(msg.content, str) else msg.content
            except Exception:
                content = _truncate(str(msg.content), limit)
                out.append(
                    ToolMessage(
                        content=content,
                        tool_call_id=msg.tool_call_id,
                        name=msg.name,
                    )
                )
                continue
            compact = _compact_tool_payload(msg.name or "", parsed)
            content = _truncate(json.dumps(compact, default=str), limit)
            out.append(
                ToolMessage(
                    content=content,
                    tool_call_id=msg.tool_call_id,
                    name=msg.name,
                )
            )
        elif isinstance(msg, AIMessage):
            if msg.tool_calls:
                out.append(
                    AIMessage(content="", tool_calls=msg.tool_calls, id=getattr(msg, "id", None))
                )
            else:
                content = msg.content
                if isinstance(content, str) and len(content) > 1500:
                    content = _truncate(content, 1500)
                out.append(AIMessage(content=content, id=getattr(msg, "id", None)))
        elif isinstance(msg, HumanMessage):
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            out.append(HumanMessage(content=_truncate(content, 4000)))
        else:
            out.append(msg)

    # Final safety net for strict chat templates
    if last_human is not None and not any(isinstance(m, HumanMessage) for m in out):
        content = last_human.content
        if isinstance(content, str):
            content = _truncate(content, 4000)
        insert_at = 1 if out and isinstance(out[0], SystemMessage) else 0
        out.insert(insert_at, HumanMessage(content=content))

    return out


def _is_failover_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    markers = (
        "429",
        "rate_limit",
        "rate limit",
        "ratelimit",
        "quota",
        "tokens per minute",
        "tpm",
        "otpm",
        "capacity",
        "404",
        "not_found",
        "model_not_found",
        "does not exist",
        "invalid_model",
        "unavailable",
        "overloaded",
        "503",
        "502",
        "timeout",
        "temporar",
        "insufficient",
    )
    return any(m in text for m in markers)


def _user_turn_message(catalog: str, question: str, intent: Intent) -> HumanMessage:
    if intent == "simple":
        hint = (
            "MODE: analytical question. "
            "Call query_data once (retry only if SQL fails). "
            "If rankings, comparisons, trends, or breakdowns would be clearer visually, "
            "also call render_chart once with the best-fitting mark "
            "(bar / line / area / point) — even if the user did not ask for a chart. "
            "Skip the chart for a single scalar answer. "
            "In your text, offer 1–2 other chart views they could ask for next."
        )
    elif intent == "forecast":
        hint = (
            "MODE: forecast — ONE PASS ONLY. "
            "1) Call query_data ONCE to build a single date/value time series "
            "(aggregate in SQL: e.g. monthly new listings COUNT, monthly avg price). "
            "Do NOT re-query the same series, explore columns, or loop per category. "
            "2) Call forecast ONCE with that series and an appropriate horizon "
            "(e.g. 36 for 3 years of monthly data, 12 for 1 year monthly). "
            "3) Optionally render_chart once (line/area) with history+forecast. "
            "4) Write a short answer grounded in the forecast tool result. "
            "If the user asks 'for each neighbourhood/category', forecast the OVERALL "
            "series (or top 1–3 categories max in separate forecast calls) — never "
            "one SQL per category in a loop."
        )
    else:
        hint = (
            "MODE: dashboard/visualize — STRICT BUDGET. "
            "Use the schema only (no probe queries). Produce AT MOST 4 charts. "
            "Pattern per chart: one simple aggregated query_data (LIMIT ≤30) "
            "+ one render_chart with auto_save=true. "
            "Total ≤4 query_data and ≤4 render_chart, then STOP and summarize. "
            "Keep SQL tiny (GROUP BY + aggregate). On SQL error, skip that chart — "
            "do not keep retrying alternate queries."
        )
    return HumanMessage(
        content=(
            "SESSION SCHEMA (exact table/column names):\n"
            f"{catalog}\n\n"
            f"{hint}\n\n"
            f"USER QUESTION: {question}"
        )
    )


_checkpointer: Optional[AsyncSqliteSaver] = None
_checkpointer_cm = None


async def get_checkpointer() -> AsyncSqliteSaver:
    global _checkpointer, _checkpointer_cm
    if _checkpointer is None:
        settings = get_settings()
        ckpt_path = settings.data_dir / "checkpoints.db"
        _checkpointer_cm = AsyncSqliteSaver.from_conn_string(str(ckpt_path))
        _checkpointer = await _checkpointer_cm.__aenter__()
    return _checkpointer


def _ai_text(msg: AIMessage) -> str:
    content = msg.content
    if isinstance(content, list):
        parts: list[str] = []
        for c in content:
            if isinstance(c, dict):
                parts.append(str(c.get("text") or c.get("content") or ""))
            else:
                parts.append(str(c))
        return " ".join(parts).strip()
    return str(content or "").strip()


def build_graph(
    session_id: str,
    model_name: Optional[str] = None,
    *,
    intent: Intent = "simple",
):
    settings = get_settings()
    tools = _build_tools(session_id, intent=intent)
    if model_name:
        primary_models = [model_name]
    elif intent == "simple":
        primary_models = settings.model_chain_fast
    else:
        primary_models = settings.model_chain

    candidates = settings.llm_candidates(primary_models)
    if not candidates:
        raise RuntimeError(
            "No LLM configured. Set LLM_API_KEY + LLM_MODELS, and/or "
            "LLM_FALLBACK_API_KEY (+ optional LLM_FALLBACK_MODELS) in backend/.env"
        )
    tool_node = ToolNode(tools)
    max_tokens = (
        settings.llm_max_tokens_simple if intent == "simple" else settings.llm_max_tokens
    )
    max_hist = (
        settings.llm_max_history_simple if intent == "simple" else settings.llm_max_history
    )

    async def agent_node(state: AgentState) -> dict:
        raw_messages = list(state["messages"])
        messages = _messages_for_llm(raw_messages, max_hist=max_hist)
        has_tool_results = any(isinstance(m, ToolMessage) for m in raw_messages)
        last_error: Optional[BaseException] = None

        for i, (api_key, base_url, model) in enumerate(candidates):
            try:
                llm = _make_llm(model, max_tokens, api_key, base_url)
                # Before any tools run, nudge the model to actually call one
                if not has_tool_results and tools:
                    bound = llm.bind_tools(tools, tool_choice="any")
                else:
                    bound = llm.bind_tools(tools)

                response = await bound.ainvoke(messages)
                has_tools = bool(getattr(response, "tool_calls", None))
                text = _ai_text(response)

                if has_tools:
                    return {"messages": [response]}

                if text:
                    return {"messages": [response]}

                # Empty reply with no tools — force a real attempt
                if not has_tool_results and tools:
                    forced = await llm.bind_tools(tools, tool_choice="any").ainvoke(
                        messages
                        + [
                            HumanMessage(
                                content=(
                                    "Your previous reply was empty. Call query_data now "
                                    "with SQL that answers USER QUESTION. Do not respond "
                                    "with empty text."
                                )
                            )
                        ]
                    )
                    if getattr(forced, "tool_calls", None) or _ai_text(forced):
                        return {"messages": [forced]}

                # After tools, empty final → ask for a short text answer (no tools)
                synth = await llm.ainvoke(
                    messages
                    + [
                        HumanMessage(
                            content=(
                                "Write a brief final answer to USER QUESTION using the "
                                "tool results above. Plain text only — do not call tools."
                            )
                        )
                    ]
                )
                if not _ai_text(synth):
                    synth = AIMessage(
                        content=(
                            "I queried the data but could not form a final summary. "
                            "Please try rephrasing the question."
                        )
                    )
                return {"messages": [synth]}
            except Exception as exc:
                last_error = exc
                has_next = i < len(candidates) - 1
                if has_next and _is_failover_error(exc):
                    continue
                if has_next:
                    continue
                raise
        assert last_error is not None
        raise last_error

    def should_continue(state: AgentState) -> str:
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and last.tool_calls:
            return "tools"
        return END

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")
    return graph


async def run_agent_stream(
    session_id: str,
    question: str,
    save_dashboard: bool = False,
) -> AsyncIterator[dict[str, Any]]:
    """Yield SSE-ready event dicts while running the agent."""
    from app.db import sqlite_store

    intent = classify_intent(question)
    catalog = schema_catalog_for_session(session_id)
    checkpointer = await get_checkpointer()
    compiled = build_graph(session_id, intent=intent).compile(checkpointer=checkpointer)

    # viz: room for ≤4 query+chart pairs + final text, not endless probing
    recursion_limit = 10 if intent == "simple" else 12 if intent == "forecast" else 18
    config = {
        "configurable": {"thread_id": session_id},
        "recursion_limit": recursion_limit,
    }
    existing = await compiled.aget_state(config)
    prior = (existing.values or {}).get("messages") if existing else None

    new_messages: list[BaseMessage] = []
    if not prior:
        new_messages.append(SystemMessage(content=SYSTEM_PROMPT))
    new_messages.append(_user_turn_message(catalog, question, intent))

    input_state = {
        "messages": new_messages,
        "session_id": session_id,
    }

    status = {
        "simple": "Looking up an answer…",
        "forecast": "Building a forecast…",
        "viz": "Preparing charts…",
    }[intent]
    yield {"event": "status", "data": {"message": status}}

    last_chart: Optional[dict[str, Any]] = None
    chart_titles: list[str] = []
    final_text = ""
    used_fallback_note = False

    try:
        async for update in compiled.astream(input_state, config=config, stream_mode="updates"):
            for node_name, payload in update.items():
                if node_name == "agent":
                    msgs = payload.get("messages") or []
                    for msg in msgs:
                        if not isinstance(msg, AIMessage):
                            continue
                        if msg.tool_calls:
                            for tc in msg.tool_calls:
                                yield {
                                    "event": "tool_start",
                                    "data": {
                                        "tool": tc["name"],
                                        "args": tc.get("args", {}),
                                    },
                                }
                        if msg.content:
                            content = msg.content
                            if isinstance(content, list):
                                content = " ".join(
                                    c.get("text", "") if isinstance(c, dict) else str(c)
                                    for c in content
                                )
                            if content and str(content).strip():
                                if not msg.tool_calls:
                                    final_text = str(content)
                                elif not final_text:
                                    final_text = str(content)
                elif node_name == "tools":
                    msgs = payload.get("messages") or []
                    for msg in msgs:
                        if not isinstance(msg, ToolMessage):
                            continue
                        try:
                            parsed = json.loads(msg.content)
                        except Exception:
                            parsed = {"raw": msg.content}
                        yield {
                            "event": "tool_result",
                            "data": {
                                "tool": msg.name,
                                "result": _summarize_tool_result(msg.name, parsed),
                            },
                        }
                        if msg.name == "render_chart" and isinstance(parsed, dict):
                            if "vega_lite_spec" in parsed:
                                last_chart = parsed
                                title = str(parsed.get("title") or "Chart")
                                chart_titles.append(title)
                                auto_save = bool(parsed.get("auto_save"))
                                chart_payload = {
                                    "vega_lite_spec": parsed["vega_lite_spec"],
                                    "title": title,
                                    "mark": parsed.get("mark"),
                                    "corrected": parsed.get("corrected", False),
                                    "auto_save": auto_save,
                                }
                                yield {"event": "chart", "data": chart_payload}
                                if auto_save:
                                    yield {
                                        "event": "canvas_chart",
                                        "data": {
                                            "id": str(uuid4()),
                                            "title": title,
                                            "chart_type": parsed.get("mark"),
                                            "vega_lite_spec": parsed["vega_lite_spec"],
                                            "question_text": question,
                                        },
                                    }
                        if msg.name == "forecast" and isinstance(parsed, dict):
                            if "forecast" in parsed:
                                yield {
                                    "event": "forecast_meta",
                                    "data": {
                                        "frequency": parsed.get("frequency"),
                                        "confidence": parsed.get("confidence"),
                                        "method": parsed.get("method"),
                                        "note": parsed.get("note"),
                                    },
                                }
    except Exception as exc:
        yield {"event": "error", "data": {"message": str(exc)}}
        if not final_text.strip() and chart_titles:
            final_text = (
                "Generated these views:\n"
                + "\n".join(f"- {t}" for t in chart_titles)
            )
        if final_text.strip():
            yield {"event": "answer", "data": {"text": final_text}}
        yield {"event": "done", "data": {}}
        return

    if not final_text.strip():
        if chart_titles:
            final_text = (
                "Here are the key views I generated from your data:\n"
                + "\n".join(f"- {t}" for t in chart_titles)
            )
        else:
            final_text = (
                "I couldn't complete that answer (the model returned no text). "
                "Please try the question again."
            )

    yield {"event": "answer", "data": {"text": final_text}}

    if save_dashboard and last_chart and "vega_lite_spec" in last_chart:
        if not last_chart.get("auto_save"):
            dashboard = sqlite_store.insert_dashboard(
                session_id=session_id,
                title=last_chart.get("title") or "Saved chart",
                question_text=question,
                chart_type=last_chart.get("mark"),
                vega_lite_spec_json=json.dumps(last_chart["vega_lite_spec"]),
            )
            yield {
                "event": "dashboard_saved",
                "data": {
                    "id": dashboard["id"],
                    "title": dashboard["title"],
                    "vega_lite_spec": last_chart["vega_lite_spec"],
                    "auto_save": False,
                },
            }

    yield {"event": "done", "data": {"used_fallback": used_fallback_note, "intent": intent}}


def _summarize_tool_result(tool: str, parsed: Any) -> Any:
    """Keep SSE payloads small."""
    if not isinstance(parsed, dict):
        return parsed
    if tool == "query_data":
        rows = parsed.get("rows") or []
        return {
            "error": parsed.get("error"),
            "message": parsed.get("message"),
            "row_count": parsed.get("row_count", len(rows)),
            "truncated": parsed.get("truncated"),
            "sql": parsed.get("sql"),
            "reasoning": parsed.get("reasoning"),
            "preview": rows[:5],
        }
    if tool == "forecast":
        fc = parsed.get("forecast") or []
        return {
            "error": parsed.get("error"),
            "reason": parsed.get("reason"),
            "confidence": parsed.get("confidence"),
            "frequency": parsed.get("frequency"),
            "method": parsed.get("method"),
            "note": parsed.get("note"),
            "forecast_preview": fc[:5],
            "horizon": parsed.get("horizon"),
        }
    if tool == "render_chart":
        return {
            "error": parsed.get("error"),
            "title": parsed.get("title"),
            "mark": parsed.get("mark"),
            "corrected": parsed.get("corrected"),
            "correction_reason": parsed.get("correction_reason"),
            "auto_save": parsed.get("auto_save", False),
            "dashboard_id": parsed.get("dashboard_id"),
            "has_spec": "vega_lite_spec" in parsed,
        }
    return parsed
