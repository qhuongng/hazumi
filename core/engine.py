import datetime
import os
import httpx
import json
import inspect
import re

from core.context import build_system_prompt, get_assistant_identity
from helpers.log import debug_enabled, get_logger, log_debug_json


LLM_MODEL = os.getenv("LLM_MODEL", "Qwen27Heretic")
SUMMARY_MODEL = os.getenv("LLM_SUMMARY_MODEL", LLM_MODEL)
LLM_API_CHAT_URL = os.getenv("LLM_API_CHAT_URL", "http://localhost:11434/v1/chat/completions")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.7"))
LLM_THINKING_PARAM_NAME = os.getenv("LLM_THINKING_PARAM_NAME", "think").strip()
LLM_CONNECT_TIMEOUT_SECONDS = float(os.getenv("LLM_CONNECT_TIMEOUT_SECONDS", "10"))
LLM_READ_TIMEOUT_SECONDS = float(os.getenv("LLM_READ_TIMEOUT_SECONDS", "300"))
LLM_WRITE_TIMEOUT_SECONDS = float(os.getenv("LLM_WRITE_TIMEOUT_SECONDS", "30"))
LLM_POOL_TIMEOUT_SECONDS = float(os.getenv("LLM_POOL_TIMEOUT_SECONDS", "30"))

FALLBACK_REPLY = "uhhh i think sth broke. help :<"

MAX_TOOL_ROUNDS = 3
LOGGER = get_logger(__name__)


def _log_llm_exception(prefix: str, exc: Exception):
    # Connection failures are common during local model startup; keep logs actionable.
    if isinstance(exc, httpx.ConnectError):
        LOGGER.error(
            "%s: failed to connect to %s (%s). Ensure Ollama/server is running and this URL is reachable.",
            prefix,
            LLM_API_CHAT_URL,
            exc,
        )
        return

    LOGGER.exception("%s: %s", prefix, exc)


def _build_common_llm_fields() -> dict:
    return {
        "stream": False,
        "temperature": LLM_TEMPERATURE,
    }


def _build_request_headers() -> dict:
    headers = {"Content-Type": "application/json"}
    if LLM_API_KEY.strip():
        headers["Authorization"] = f"Bearer {LLM_API_KEY.strip()}"
    return headers


def _build_http_timeout() -> httpx.Timeout:
    return httpx.Timeout(
        connect=LLM_CONNECT_TIMEOUT_SECONDS,
        read=LLM_READ_TIMEOUT_SECONDS,
        write=LLM_WRITE_TIMEOUT_SECONDS,
        pool=LLM_POOL_TIMEOUT_SECONDS,
    )


def _normalize_for_dedupe(value: str) -> str:
    text = re.sub(r"<@!?\d+>", "", str(value or ""))
    text = " ".join(text.split())
    return text.strip().lower()


def _is_compute_error(response_text: str) -> bool:
    text = str(response_text or "").lower()
    return "compute error" in text or "insufficient memory" in text


def _is_unsupported_parameter_error(response_text: str, parameter_name: str) -> bool:
    text = str(response_text or "").lower()
    param = str(parameter_name or "").strip().lower()
    if not param or param not in text:
        return False
    return any(
        token in text
        for token in (
            "unsupported",
            "unknown",
            "unrecognized",
            "not permitted",
            "extra inputs",
            "invalid",
        )
    )


def _apply_thinking_payload_field(payload: dict, thinking_enabled: bool | None) -> tuple[dict, bool]:
    if thinking_enabled is None:
        return payload, False

    field_name = str(LLM_THINKING_PARAM_NAME or "").strip()
    if not field_name:
        return payload, False

    payload[field_name] = bool(thinking_enabled)
    return payload, True


def _trim_history(history: list[dict]) -> list[dict]:
    return list(history or [])


def _write_debug_messages_text(messages: list[dict]) -> None:
    file_name = f"debug_messages_{datetime.datetime.now().isoformat()}.readable.txt"
    lines: list[str] = []

    for idx, item in enumerate(messages):
        role = str(item.get("role") or "")
        content = str(item.get("content") or "")
        header = f"TURN {idx} | role: {role}"
        if role == "tool" and item.get("tool_name"):
            header += f" | tool_name: {item.get('tool_name')}"

        lines.append("============================================================")
        lines.append(header)
        lines.append("------------------------------------------------------------")
        lines.append(content)
        lines.append("")

    with open(file_name, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _sanitize_summary_text(text: str) -> str:
    cleaned_lines: list[str] = []
    for line in str(text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        line = re.sub(r"^[-*#>\d\.)\s]+", "", line)
        line = re.sub(r"\*\*(.*?)\*\*", r"\1", line)
        line = re.sub(r"\[(.*?)\]", r"\1", line)
        if ":" in line and line.split(":", 1)[0].strip().lower() in {
            "summary",
            "key facts",
            "preferences",
            "tasks",
            "unresolved items",
            "key entities",
        }:
            line = line.split(":", 1)[1].strip()
        if line:
            cleaned_lines.append(line)

    plain = " ".join(cleaned_lines)
    plain = re.sub(r"\s+", " ", plain).strip()

    if not plain:
        return ""

    return plain


def _reduce_summary_transcript(transcript: str) -> str:
    return str(transcript or "").strip()


def _json_type_for_annotation(annotation) -> str:
    if annotation in (int,):
        return "integer"
    if annotation in (float,):
        return "number"
    if annotation in (bool,):
        return "boolean"
    return "string"


def _build_tool_schema(tool_fn) -> dict:
    signature = inspect.signature(tool_fn)
    properties: dict = {}
    required: list[str] = []

    for param in signature.parameters.values():
        if param.kind not in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        ):
            continue
        if param.name.startswith("_"):
            continue

        json_type = _json_type_for_annotation(param.annotation)
        properties[param.name] = {"type": json_type}
        if param.default is inspect.Parameter.empty:
            required.append(param.name)

    tool_description = (inspect.getdoc(tool_fn) or "").strip()
    function_spec = {
        "name": tool_fn.__name__,
        "description": tool_description or f"Call tool `{tool_fn.__name__}`.",
        "parameters": {
            "type": "object",
            "properties": properties,
            "additionalProperties": False,
        },
    }
    if required:
        function_spec["parameters"]["required"] = required

    return {"type": "function", "function": function_spec}


def _build_tools(tools: list | None) -> list[dict]:
    if not tools:
        return []
    schemas: list[dict] = []
    for tool_fn in tools:
        try:
            schemas.append(_build_tool_schema(tool_fn))
        except Exception as exc:
            LOGGER.exception("Failed to build schema for tool `%s`: %s", getattr(tool_fn, "__name__", tool_fn), exc)
    return schemas


def _extract_response_message(data: dict) -> dict:
    choices = data.get("choices") or []
    if not choices:
        return {}
    first = choices[0] or {}
    return first.get("message") or {}


async def summarize_transcript(transcript: str, batch_size: int = 20) -> str | None:
    assistant_identity = get_assistant_identity()
    prompt = (
        f"Summarize this {batch_size}-message conversation chunk for future context in natural language. "
        "Input lines follow this exact format: msg_id <id> - username: message OR msg_id <id> (reply to <id>) - username: message. "
        "Use that structure to infer who said what and reply relationships. "
        "Include major events and key entities only when they matter for future replies. "
        "Return plain text in a single paragraph; no markdown, bullets, headings, labels, or list formatting. "
        f"The assistant persona is {assistant_identity} from SOUL.md, so do not refer to that assistant in third person."
    )

    try:
        transcript_text = str(transcript or "")
        base_payload = {
            "model": SUMMARY_MODEL,
            "messages": [
                {"role": "system", "content": "You create compact memory summaries."},
                {"role": "user", "content": f"{prompt}\n\n{transcript_text}"},
            ],
            **_build_common_llm_fields(),
        }
        # log_debug_json(LOGGER, "[llm.summary.payload]", base_payload)

        async with httpx.AsyncClient() as http_client:
            response = None
            payload = base_payload
            timeout_retry_used = False
            for attempt in range(2):
                try:
                    response = await http_client.post(
                        LLM_API_CHAT_URL,
                        json=payload,
                        headers=_build_request_headers(),
                        timeout=_build_http_timeout(),
                    )
                except httpx.ReadTimeout:
                    if not timeout_retry_used:
                        timeout_retry_used = True
                        LOGGER.warning(
                            "Summary model request timed out (read_timeout=%ss); retrying once",
                            LLM_READ_TIMEOUT_SECONDS,
                        )
                        continue
                    raise
                if response.status_code < 400:
                    break

                LOGGER.error(
                    "Summary model call failed status=%s body=%s",
                    response.status_code,
                    response.text,
                )
                should_retry_compute = (
                    attempt == 0
                    and response.status_code >= 500
                    and _is_compute_error(response.text)
                )
                if should_retry_compute:
                    reduced_transcript = _reduce_summary_transcript(transcript_text)
                    LOGGER.warning(
                        "Retrying summary with reduced transcript after compute error (chars=%s -> %s)",
                        len(transcript_text),
                        len(reduced_transcript),
                    )
                    payload = {
                        "model": SUMMARY_MODEL,
                        "messages": [
                            {"role": "system", "content": "You create compact memory summaries."},
                            {"role": "user", "content": f"{prompt}\n\n{reduced_transcript}"},
                        ],
                        **_build_common_llm_fields(),
                    }
                    continue

                response.raise_for_status()

        data = response.json()
        # log_debug_json(LOGGER, "[llm.summary.response]", data)
        summary = _sanitize_summary_text((_extract_response_message(data).get("content") or "").strip())
        return summary or None
    except Exception as exc:
        _log_llm_exception("Summary generation error", exc)
        return None


async def process_message_with_history(
    user_id: str,
    user_name: str,
    text: str,
    history: list[dict],
    context_note: str = "",
    tools: list | None = None,
    thinking_enabled: bool | None = None,
) -> str:
    try:
        system = build_system_prompt(user_id=user_id, user_name=user_name)
    except Exception as exc:
        LOGGER.exception("Context load error: %s", exc)
        system = "You are a helpful assistant."

    if context_note:
        system = f"{system}\n\n# Discord context\n\n{context_note}"

    # if debug_enabled():
    #     LOGGER.debug(
    #         "[llm.system_prompt] user_id=%s user_name=%s\n%s",
    #         user_id,
    #         user_name,
    #         system,
    #     )

    normalized_text = _normalize_for_dedupe(text)
    filtered_history = _trim_history(history)
    if filtered_history:
        last = filtered_history[-1]
        if (
            last.get("role") == "user"
            and _normalize_for_dedupe(str(last.get("content") or "")) == normalized_text
        ):
            filtered_history = filtered_history[:-1]

    messages = [{"role": "system", "content": system}]
    messages += [
        {"role": m["role"], "content": str(m["content"])}
        for m in filtered_history
    ]
    messages.append({"role": "user", "content": text})
    active_tools = tools or []
    chat_tools = _build_tools(active_tools)
    tool_map = {fn.__name__: fn for fn in active_tools}
    LOGGER.info(
        "[tooling] prepared tool map user_id=%s user_name=%s tools=%s",
        user_id,
        user_name,
        list(tool_map.keys()),
    )
    # if debug_enabled():
        # log_debug_json(LOGGER, "[tooling.schemas]", chat_tools)

    final_text = ""
    for _ in range(MAX_TOOL_ROUNDS):
        try:
            base_payload = {
                "model": LLM_MODEL,
                "messages": messages,
                "tools": chat_tools,
                **_build_common_llm_fields(),
            }
            base_payload, think_field_included = _apply_thinking_payload_field(base_payload, thinking_enabled)
            log_debug_json(LOGGER, "[llm.chat.discord_content]", context_note)

            # Write messages into a readable text file for debugging
            # _write_debug_messages_text(messages)

            async with httpx.AsyncClient() as http_client:
                response = None
                payload = base_payload
                timeout_retry_used = False
                think_field_retry_used = False
                for attempt in range(2):
                    try:
                        response = await http_client.post(
                            LLM_API_CHAT_URL,
                            json=payload,
                            headers=_build_request_headers(),
                            timeout=_build_http_timeout(),
                        )
                    except httpx.ReadTimeout:
                        if not timeout_retry_used:
                            timeout_retry_used = True
                            LOGGER.warning(
                                "Model request timed out user_id=%s (read_timeout=%ss); retrying once",
                                user_id,
                                LLM_READ_TIMEOUT_SECONDS,
                            )
                            continue
                        raise
                    if response.status_code < 400:
                        break

                    LOGGER.error(
                        "Model call failed status=%s body=%s",
                        response.status_code,
                        response.text,
                    )
                    should_retry_without_think_field = (
                        think_field_included
                        and not think_field_retry_used
                        and _is_unsupported_parameter_error(response.text, LLM_THINKING_PARAM_NAME)
                    )
                    if should_retry_without_think_field:
                        think_field_retry_used = True
                        payload = dict(payload)
                        payload.pop(LLM_THINKING_PARAM_NAME, None)
                        LOGGER.warning(
                            "Provider rejected `%s` payload field; retrying request without it user_id=%s",
                            LLM_THINKING_PARAM_NAME,
                            user_id,
                        )
                        continue

                    should_retry_compute = (
                        attempt == 0
                        and response.status_code >= 500
                        and _is_compute_error(response.text)
                    )
                    if should_retry_compute:
                        LOGGER.warning(
                            "Retrying with reduced llama payload after compute error user_id=%s",
                            user_id,
                        )
                        reduced_messages = [messages[0], messages[-1]] if len(messages) >= 2 else list(messages)
                        payload = {
                            "model": LLM_MODEL,
                            "messages": reduced_messages,
                            **_build_common_llm_fields(),
                        }
                        continue

                    response.raise_for_status()

                data = response.json()
                log_debug_json(LOGGER, "[llm.chat.response]", data)
        except Exception as exc:
            _log_llm_exception("Model call error", exc)
            final_text = final_text or FALLBACK_REPLY
            break

        msg = _extract_response_message(data)
        msg_content = msg.get("content") or ""
        msg_tool_calls = msg.get("tool_calls") or []
        messages.append({"role": "assistant", "content": msg_content, **(
            {"tool_calls": msg_tool_calls}
            if msg_tool_calls else {}
        )})

        if not msg_tool_calls:
            final_text = msg_content
            break

        for tool_call in msg_tool_calls:
            tool_call_id = (tool_call.get("id") or "").strip()
            fn_name = ((tool_call.get("function") or {}).get("name") or "").strip()
            fn_args = (tool_call.get("function") or {}).get("arguments") or {}
            if isinstance(fn_args, str):
                try:
                    fn_args = json.loads(fn_args)
                except Exception:
                    fn_args = {}
            if not isinstance(fn_args, dict):
                fn_args = {}

            fn = tool_map.get(fn_name)
            if fn:
                try:
                    LOGGER.info(
                        "[tooling] invoking tool user_id=%s tool=%s args_keys=%s",
                        user_id,
                        fn_name,
                        list(fn_args.keys()),
                    )
                    if "_user_id" in fn.__code__.co_varnames:
                        fn_args["_user_id"] = user_id
                    if "_user_name" in fn.__code__.co_varnames:
                        fn_args["_user_name"] = user_name
                    result = await fn(**fn_args)
                    LOGGER.info(
                        "[tooling] tool success user_id=%s tool=%s result_len=%s",
                        user_id,
                        fn_name,
                        len(str(result)),
                    )
                except Exception as exc:
                    LOGGER.exception(
                        "[tooling] tool error user_id=%s tool=%s error=%s",
                        user_id,
                        fn_name,
                        exc,
                    )
                    result = f"Tool {fn_name} failed: {exc}"
            else:
                LOGGER.warning("[tooling] unknown tool requested user_id=%s tool=%s", user_id, fn_name)
                result = f"Unknown tool: {fn_name}"

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": str(result),
            })

    return final_text or FALLBACK_REPLY
