"""LLM configuration constants."""
import os


# model configuration
LLM_MODEL = os.getenv("LLM_MODEL", "Qwen27Heretic")
LLM_API_CHAT_URL = os.getenv("LLM_API_CHAT_URL", "http://localhost:11434/v1/chat/completions")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.7"))
LLM_THINKING_PARAM_NAME = os.getenv("LLM_THINKING_PARAM_NAME", "think").strip()

# timeout configuration
LLM_CONNECT_TIMEOUT_SECONDS = float(os.getenv("LLM_CONNECT_TIMEOUT_SECONDS", "10"))
LLM_READ_TIMEOUT_SECONDS = float(os.getenv("LLM_READ_TIMEOUT_SECONDS", "300"))
LLM_WRITE_TIMEOUT_SECONDS = float(os.getenv("LLM_WRITE_TIMEOUT_SECONDS", "30"))
LLM_POOL_TIMEOUT_SECONDS = float(os.getenv("LLM_POOL_TIMEOUT_SECONDS", "30"))

# behavior configuration
MAX_TOOL_ROUNDS = 3
FALLBACK_REPLY = "uhhh i think sth broke. help :<"
