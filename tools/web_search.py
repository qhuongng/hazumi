import asyncio
import re
import httpx
import trafilatura

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
        ".gov", ".edu", "wikipedia.org", "britannica.com", "reuters.com",
        "apnews.com", "who.int", "nih.gov", "docs.", "developer.", "github.com",
    )
    low_signal = ("fandom.com", "pinterest.", "quora.com")
    if any(t in lowered for t in trust_boost):
        return 0.12
    if any(t in lowered for t in low_signal):
        return -0.06
    return 0.0


def _score_result(query: str, item: dict) -> float:
    query_tokens = _tokenize(query)
    title = str(item.get("title") or "")
    snippet = str(item.get("body") or item.get("snippet") or "")
    url = str(item.get("href") or item.get("url") or "")
    combined_text = title + " " + snippet

    title_overlap = _overlap_score(query_tokens, title)
    snippet_overlap = _overlap_score(query_tokens, snippet)
    phrase_bonus = 0.1 if query.lower() in combined_text.lower() else 0.0
    domain_bonus = _domain_prior(url)

    score = (0.45 * title_overlap) + (0.28 * snippet_overlap) + phrase_bonus + domain_bonus
    return max(0.0, min(1.0, score))


def _rank_results(query: str, results: list[dict]) -> list[dict]:
    ranked = []
    for item in results:
        score = _score_result(query, item)
        cloned = dict(item)
        cloned["_score"] = score
        ranked.append(cloned)
    ranked.sort(key=lambda r: r.get("_score", 0.0), reverse=True)
    return ranked


async def _fetch_with_trafilatura(url: str) -> str:
    """Fetch a URL and extract clean text using trafilatura."""
    if not url:
        return ""
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
            response = await client.get(url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; HazumiBot/1.0)"
            })
            response.raise_for_status()
            content_type = (response.headers.get("content-type") or "").lower()
            if "html" not in content_type and "text" not in content_type:
                return ""
            # trafilatura works on raw html strings
            extracted = trafilatura.extract(
                response.text,
                include_comments=False,
                include_tables=False,
                no_fallback=False,
            )
            if not extracted:
                return ""
            # truncate to keep context reasonable (~500-700 tokens)
            return extracted[:2500]
    except Exception:
        return ""


async def web_search(query: str, max_results: int = 5) -> str:
    """Run a web search, rank results, fetch and extract content from top 3.
    
    Use when the user query indicates they want up-to-date, time-sensitive information, or they asked about something you're unsure about.
    """

    normalized_query = (query or "").strip()
    if not normalized_query:
        return "Please provide a non-empty search query."

    normalized_max = max(3, min(int(max_results or 5), 8))

    try:
        results = await asyncio.to_thread(_search_sync, normalized_query, normalized_max)
    except Exception as exc:
        return f"Web search failed: {exc}"

    if not results:
        return "No results found."

    ranked = _rank_results(normalized_query, results)
    top3 = ranked[:3]

    # fetch all 3 concurrently
    urls = [(item.get("href") or item.get("url") or "").strip() for item in top3]
    excerpts = await asyncio.gather(*[_fetch_with_trafilatura(url) for url in urls])

    sections = []
    for idx, (item, excerpt) in enumerate(zip(top3, excerpts), start=1):
        title = (item.get("title") or "Untitled").strip()
        url = urls[idx - 1]
        snippet = (item.get("body") or item.get("snippet") or "").strip()

        block = f"### Result {idx}: {title}"
        if url:
            block += f"\nURL: {url}"
        if excerpt:
            block += f"\n\n{excerpt}"
        elif snippet:
            # fallback to ddgs snippet if fetch failed
            block += f"\n\n{snippet}"

        sections.append(block)

    return "\n\n---\n\n".join(sections)