import os

from ollama import AsyncClient

from core.context import build_system_prompt


OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3.5:9b")
SUMMARY_MODEL = os.getenv("OLLAMA_SUMMARY_MODEL", OLLAMA_MODEL)
OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "10m")
FALLBACK_REPLY = "uhhh i think sth broke. help :<"
MAX_TOOL_ROUNDS = 6

client = AsyncClient()


async def summarize_transcript(transcript: str, batch_size: int = 20) -> str | None:
    prompt = (
        f"Summarize this {batch_size}-message conversation chunk for long-term context. "
        "Keep it concise and useful for future replies. Include key facts, preferences, tasks, and unresolved items. "
        "Use plain text and avoid any formatting."
    )

    try:
        response = await client.chat(
            model=SUMMARY_MODEL,
            messages=[
                {"role": "system", "content": "You create compact memory summaries."},
                {"role": "user", "content": f"{prompt}\n\n{transcript}"},
            ],
            think=False,
            keep_alive=OLLAMA_KEEP_ALIVE,
        )
        summary = (response.message.content or "").strip()
        return summary or None
    except Exception as exc:
        print(f"Summary generation error: {exc}")
        return None


async def process_message_with_history(
    user_id: str,
    text: str,
    history: list[dict],
    context_note: str = "",
    tools: list | None = None,
) -> str:
    try:
        system = build_system_prompt()
    except Exception as exc:
        print(f"Context load error: {exc}")
        system = "You are a helpful assistant."

    if context_note:
        system = f"{system}\n\n## Discord context\n{context_note}"

    messages = [{"role": "system", "content": system}]
    messages += [{"role": m["role"], "content": m["content"]} for m in history]
    messages.append({"role": "user", "content": text})
    active_tools = tools or []
    tool_map = {fn.__name__: fn for fn in active_tools}

    final_text = ""
    for _ in range(MAX_TOOL_ROUNDS):
        try:
            response = await client.chat(
                model=OLLAMA_MODEL,
                messages=messages,
                tools=active_tools,
                think=False,
                options={"temperature": 0.8},
                keep_alive=OLLAMA_KEEP_ALIVE,
            )
        except Exception as exc:
            print(f"Model call error: {exc}")
            final_text = final_text or FALLBACK_REPLY
            break

        msg = response.message
        messages.append({"role": "assistant", "content": msg.content or "", **(
            {"tool_calls": [tc.model_dump() for tc in msg.tool_calls]}
            if msg.tool_calls else {}
        )})

        if not msg.tool_calls:
            final_text = msg.content or ""
            break

        for tool_call in msg.tool_calls:
            fn_name = tool_call.function.name
            fn_args = tool_call.function.arguments or {}
            if not isinstance(fn_args, dict):
                fn_args = {}

            fn = tool_map.get(fn_name)
            if fn:
                try:
                    if "_user_id" in fn.__code__.co_varnames:
                        fn_args["_user_id"] = user_id
                    result = await fn(**fn_args)
                except Exception as exc:
                    result = f"Tool {fn_name} failed: {exc}"
            else:
                result = f"Unknown tool: {fn_name}"

            messages.append({
                "role": "tool",
                "tool_name": fn_name,
                "content": str(result),
            })

    return final_text or FALLBACK_REPLY
