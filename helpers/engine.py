import inspect

from constants.config.llm import LLM_THINKING_PARAM_NAME
from helpers.log import get_logger

LOGGER = get_logger(__name__)


def build_common_llm_fields() -> dict:
    return {"stream": False}


def apply_thinking_payload_field(payload: dict, thinking_enabled: bool | None) -> tuple[dict, bool]:
    if thinking_enabled is None:
        return payload, False

    field_name = str(LLM_THINKING_PARAM_NAME or "").strip()
    if not field_name:
        return payload, False

    payload[field_name] = bool(thinking_enabled)
    return payload, True


def json_type_for_annotation(annotation) -> str:
    if annotation in (int,):
        return "integer"
    if annotation in (float,):
        return "number"
    if annotation in (bool,):
        return "boolean"
    return "string"


def build_tool_schema(tool_fn) -> dict:
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

        json_type = json_type_for_annotation(param.annotation)
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


def build_tools(tools: list | None) -> list[dict]:
    if not tools:
        return []
    schemas: list[dict] = []
    for tool_fn in tools:
        try:
            schemas.append(build_tool_schema(tool_fn))
        except Exception as exc:
            LOGGER.exception("Failed to build schema for tool `%s`: %s", getattr(tool_fn, "__name__", tool_fn), exc)
    return schemas
