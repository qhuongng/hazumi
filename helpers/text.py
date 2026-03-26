def split_message_chunks(text: str, max_len: int = 1990) -> list[str]:
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
