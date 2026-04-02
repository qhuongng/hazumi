import httpx
import json
import inspect
import re

from constants.config.llm import (
    LLM_MODEL,
    LLM_API_CHAT_URL,
    LLM_THINKING_PARAM_NAME,
    LLM_READ_TIMEOUT_SECONDS,
    MAX_TOOL_ROUNDS,
    FALLBACK_REPLY,
)
from core.context import build_system_prompt
from helpers import http as http_helpers
from helpers.log import get_logger, log_messages, log_tool_use


LOGGER = get_logger(__name__)


def _log_llm_exception(prefix: str, exc: Exception):
    # connection failures are common during local model startup; keep logs actionable
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
    }


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

    # discord context is a user message after the system message
    # log_prompt(LOGGER, system, context_note)

    normalized_text = _normalize_for_dedupe(text)
    if thinking_enabled is False:
        normalized_text = "/no_think " + normalized_text
    filtered_history = list(history or [])
    if filtered_history:
        last = filtered_history[-1]
        if (
            last.get("role") == "user"
            and _normalize_for_dedupe(str(last.get("content") or "")) == normalized_text
        ):
            filtered_history = filtered_history[:-1]

    messages = [{"role": "system", "content": system}]
    if context_note:
        messages.append({"role": "user", "content": f"# Discord context\n\n{context_note}"})
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
            log_messages(LOGGER, messages)

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
                            headers=http_helpers.build_request_headers(),
                            timeout=http_helpers.build_http_timeout(),
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
                    log_tool_use(LOGGER, f"CALL: {fn_name}", {"args": fn_args, "user_id": user_id})

                    if "_user_id" in fn.__code__.co_varnames:
                        fn_args["_user_id"] = user_id
                    if "_user_name" in fn.__code__.co_varnames:
                        fn_args["_user_name"] = user_name
                    result = await fn(**fn_args)

                    log_tool_use(LOGGER, f"RESULT: {fn_name}", {"result": result})
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
