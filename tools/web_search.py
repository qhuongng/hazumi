import asyncio
from html import unescape
import re

import httpx
from ddgs import DDGS


def _search_sync(query: str, max_results: int = 5) -> list[dict]:
    return DDGS().text(query=query, max_results=max_results)


def _tokenize(text: str) -> set[str]:
    stopwords = {
        "the", "a", "an", "is", "am", "are", "was", "were", "to", "of", "and", "in", "on", "for",
        "with", "that", "this", "it", "i", "my", "me", "we", "our", "you", "your", "they", "them",
        "he", "she", "at", "as", "be", "or", "by", "from", "about", "what", "how", "who", "when",
    }
    tokens = set(re.findall(r"[a-z0-9]+", (text or "").lower()))
    return {t for t in tokens if t not in stopwords and len(t) > 1}


def _overlap_score(query_tokens: set[str], text: str) -> float:
    if not query_tokens:
        return 0.0
    text_tokens = _tokenize(text)
    if not text_tokens:
        return 0.0
    return len(query_tokens & text_tokens) / len(query_tokens)


def _domain_prior(url: str) -> float:
    lowered = (url or "").lower()
    if not lowered:
        return 0.0

    trust_boost = (
        ".gov", ".edu", "wikipedia.org", "britannica.com", "reuters.com", "apnews.com", "who.int", "nih.gov",
        "docs.", "developer.", "github.com",
    )
    low_signal = ("fandom.com", "pinterest.", "quora.com")

    if any(t in lowered for t in trust_boost):
        return 0.12
    if any(t in lowered for t in low_signal):
        return -0.06
    return 0.0


def _snippet_quality_penalty(snippet: str) -> float:
    if not snippet:
        return 0.1
    s = _normalize_snippet(snippet)
    if len(s) < 40:
        return 0.08
    # penalize obvious keyword stuffing / low readability.
    unique_ratio = len(set(s.lower().split())) / max(len(s.split()), 1)
    if unique_ratio < 0.35:
        return 0.06
    return 0.0


def _score_result(query: str, item: dict) -> float:
    query_tokens = _tokenize(query)
    title = str(item.get("title") or "")
    snippet = str(item.get("body") or item.get("snippet") or "")
    url = str(item.get("href") or item.get("url") or "")

    title_overlap = _overlap_score(query_tokens, title)
    snippet_overlap = _overlap_score(query_tokens, snippet)
    phrase_bonus = 0.1 if query.lower() in (title + " " + snippet).lower() else 0.0
    domain_bonus = _domain_prior(url)
    quality_penalty = _snippet_quality_penalty(snippet)

    score = (0.48 * title_overlap) + (0.30 * snippet_overlap) + phrase_bonus + domain_bonus - quality_penalty
    return max(0.0, min(1.0, score))


def _confidence_label(score: float) -> str:
    if score >= 0.75:
        return "high"
    if score >= 0.5:
        return "medium"
    return "low"


def _rank_results(query: str, results: list[dict]) -> list[dict]:
    ranked = []
    for item in results:
        score = _score_result(query, item)
        cloned = dict(item)
        cloned["_score"] = score
        ranked.append(cloned)
    ranked.sort(key=lambda r: r.get("_score", 0.0), reverse=True)
    return ranked


def _normalize_snippet(text: str) -> str:
    cleaned = " ".join(text.split())
    cleaned = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", cleaned)
    cleaned = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", cleaned)
    cleaned = re.sub(r"([A-Za-z])'s(?=[a-z])", r"\1's ", cleaned)
    cleaned = re.sub(
        r"(?<=[a-z])(was|is|are|were|born|age|with|from|into|onto|over|under|about|after|before|during)\b",
        r" \1",
        cleaned,
    )
    return " ".join(cleaned.split())


def _extract_text_from_html(html: str) -> str:
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<noscript\b[^>]*>.*?</noscript>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    text = _normalize_snippet(text)
    return text


def _best_excerpt(text: str, query: str, max_chars: int = 700) -> str:
    if not text:
        return ""

    query_tokens = _tokenize(query)
    sentences = re.split(r"(?<=[.!?])\s+", text)
    scored: list[tuple[float, str]] = []
    for s in sentences:
        if len(s) < 30:
            continue
        overlap = _overlap_score(query_tokens, s)
        scored.append((overlap, s))

    scored.sort(key=lambda x: x[0], reverse=True)
    picked = [s for _, s in scored[:3]]
    if not picked:
        picked = [text[:max_chars]]

    excerpt = " ".join(picked)
    if len(excerpt) > max_chars:
        excerpt = excerpt[: max_chars - 3].rstrip() + "..."
    return excerpt


async def _fetch_top_result_excerpt(url: str, query: str) -> str:
    if not url:
        return ""

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
            response = await client.get(url)
            response.raise_for_status()
            content_type = (response.headers.get("content-type") or "").lower()
            if "html" not in content_type and "text" not in content_type:
                return ""
            raw_text = _extract_text_from_html(response.text)
            return _best_excerpt(raw_text, query=query)
    except Exception:
        return ""


def _to_markdown(results: list[dict]) -> str:
    if not results:
        return "No relevant web results found."

    lines = []
    for idx, item in enumerate(results, start=1):
        title = (item.get("title") or "Untitled").strip()
        url = (item.get("href") or item.get("url") or "").strip()
        snippet = _normalize_snippet((item.get("body") or item.get("snippet") or "").strip())
        score = float(item.get("_score") or 0.0)
        confidence = _confidence_label(score)

        if url:
            line = f"{idx}. [{title}]({url})"
        else:
            line = f"{idx}. {title}"
        line += f" (score: {score:.2f}, confidence: {confidence})"

        if snippet:
            line += f"\n   - {snippet}"

        lines.append(line)

    return "\n".join(lines)


async def web_search(query: str, max_results: int = 5) -> str:
    """Run a lightweight web text search and return markdown-formatted results."""

    normalized_query = (query or "").strip()
    if not normalized_query:
        return "Please provide a non-empty search query."

    normalized_max = max(1, min(int(max_results or 5), 8))

    try:
        results = await asyncio.to_thread(_search_sync, normalized_query, normalized_max)
    except Exception as exc:
        return f"Web search failed: {exc}"

    ranked = _rank_results(normalized_query, results)
    top = ranked[0] if ranked else {}
    top_title = (top.get("title") or "Untitled").strip()
    top_url = (top.get("href") or top.get("url") or "").strip()
    top_score = float(top.get("_score") or 0.0)
    top_conf = _confidence_label(top_score)
    excerpt = await _fetch_top_result_excerpt(top_url, normalized_query)

    sections = []
    if top_url:
        sections.append(
            "Top result:\n"
            f"- [{top_title}]({top_url})\n"
            f"- score: {top_score:.2f} ({top_conf} confidence)"
        )
    if excerpt:
        sections.append(f"Top result excerpt:\n- {excerpt}")

    sections.append("Ranked results:\n" + _to_markdown(ranked))

    return "\n\n".join(sections)
