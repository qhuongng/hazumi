import os


# model configuration
LLM_MODEL = "Qwen3.5-9B-Q4_K_M"
LLM_API_CHAT_URL = "http://localhost:8080/v1/chat/completions"
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_THINKING_PARAM_NAME = "think"

# timeout configuration
LLM_CONNECT_TIMEOUT_SECONDS = 10
LLM_READ_TIMEOUT_SECONDS = 180
LLM_WRITE_TIMEOUT_SECONDS = 30
LLM_POOL_TIMEOUT_SECONDS = 30

# behavior configuration
MAX_TOOL_ROUNDS = 3
FALLBACK_REPLY = "~~TRUCK-KUN~~ AN EXCEPTION HIT ME!!! HELP!!! ;;A;;"
