import re


def split_message_chunks(text: str, max_len: int = 1990) -> list[str]:
    """Split text into chunks that are at most max_len characters, trying to split on word boundaries."""
    chunks: list[str] = []
    words = text.split()

    if not words:
        return [text[:max_len]] if text else [""]

    current = ""
    for word in words:
        if len(word) > max_len:
            if current:
                chunks.append(current)
                current = ""
            for i in range(0, len(word), max_len):
                chunks.append(word[i:i + max_len])
            continue

        candidate = f"{current} {word}" if current else word
        if len(candidate) <= max_len:
            current = candidate
        else:
            chunks.append(current)
            current = word

    if current:
        chunks.append(current)

    return chunks


def normalize_for_dedupe(value: str) -> str:
    """Normalize user text for duplicate detection in chat history."""
    text = re.sub(r"<@!?\d+>", "", str(value or ""))
    text = " ".join(text.split())
    return text.strip().lower()


def strip_thought_blocks(text: str) -> str:
    """Remove Gemma-style internal thought blocks and keep visible answer only."""
    if not text:
        return ""
    s = str(text)
    try:
        # remove blocks like: <|channel>thought ... <channel|>
        s = re.sub(r"(?is)<\|channel\>thought.*?<channel\|>", "", s)
        # keep line breaks for texting rhythm, but prevent paragraph-style blank lines.
        s = "\n".join([line for line in s.splitlines()]).strip()
        s = re.sub(r"\n[ \t]*\n+", "\n", s)
    except Exception:
        return s.strip()
    return s.strip()
