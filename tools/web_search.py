import asyncio
import re
import logging
import httpx
import trafilatura
from datetime import datetime

from ddgs import DDGS


logging.getLogger("trafilatura").setLevel(logging.ERROR)



def _normalize_search_mode(search_mode: str | None) -> str:
    mode = str(search_mode or "relevant").strip().lower()
    return mode if mode in {"relevant", "latest"} else "relevant"


def _dedupe_results(results: list[dict]) -> list[dict]:
    deduped: list[dict] = []
    seen: set[str] = set()
    for item in results or []:
        url = str(item.get("href") or item.get("url") or "").strip().lower()
        title = str(item.get("title") or "").strip().lower()
        key = url or title
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _safe_news_search(ddgs: DDGS, query: str, max_results: int) -> list[dict]:
    try:
        items = ddgs.news(query=query, max_results=max_results)
    except Exception:
        return []

    normalized: list[dict] = []
    for item in items or []:
        normalized.append({
            "title": item.get("title"),
            "body": item.get("body") or item.get("excerpt") or item.get("description"),
            "href": item.get("url") or item.get("href"),
            "date": item.get("date") or item.get("published"),
            "source": item.get("source"),
        })
    return _dedupe_results(normalized)


def _safe_text_search(ddgs: DDGS, query: str, max_results: int) -> list[dict]:
    # Some DDGS backends intermittently fail with DecodeError (seen on bing/news).
    # Try a few backend/query variants before giving up.
    backends = ["auto", "html", "lite"]
    query_variants = [query, f"{query} latest"]

    for backend in backends:
        for q in query_variants:
            try:
                items = ddgs.text(query=q, max_results=max_results, backend=backend)
                if items:
                    return _dedupe_results(list(items))
            except TypeError:
                # Older ddgs versions may not support backend kwarg.
                try:
                    items = ddgs.text(query=q, max_results=max_results)
                    if items:
                        return _dedupe_results(list(items))
                except Exception:
                    continue
            except Exception:
                continue
    return []


def _search_sync(query: str, max_results: int = 5, search_mode: str = "relevant") -> list[dict]:
    """Run DDGS search with mode-aware strategy.

    - relevant: normal web text search
    - latest: prefer DDGS news results, then fall back to recency-biased text search
    """
    mode = _normalize_search_mode(search_mode)
    with DDGS() as ddgs:
        if mode == "latest":
            news_results = _safe_news_search(ddgs, query, max_results)
            if news_results:
                return news_results

            # fallback: bias text search toward recent results
            year = datetime.utcnow().year
            latest_text = _safe_text_search(ddgs, f"{query} {year}", max_results)
            if latest_text:
                return latest_text

            return _safe_text_search(ddgs, query, max_results)

        return _safe_text_search(ddgs, query, max_results)


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
        "apnews.com", "who.int", "nih.gov", "docs.", "developer.", "github.com", "fandom.com",
    )
    low_signal = ("pinterest.", "quora.com")
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


async def web_search(query: str, max_results: int = 5, search_mode: str = "relevant") -> str:
    """Run a web search, rank results, fetch and extract content from top 3.

    Use when the user query indicates they want up-to-date, time-sensitive information, or they asked about something you're unsure about.

    Parameters:
    - query: search terms
    - max_results: number of candidates to pull before selecting top excerpts (3-8)
    - search_mode: "relevant" (default) or "latest"
    """

    normalized_query = (query or "").strip()
    if not normalized_query:
        return "Please provide a non-empty search query."

    normalized_max = max(3, min(int(max_results or 5), 8))
    normalized_mode = _normalize_search_mode(search_mode)

    try:
        results = await asyncio.to_thread(_search_sync, normalized_query, normalized_max, normalized_mode)
    except Exception as exc:
        return f"Web search failed: {exc}"

    if not results:
        return "No results found."

    ranked = _rank_results(normalized_query, results) if normalized_mode == "relevant" else list(results)
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
        date = (item.get("date") or "").strip() if isinstance(item.get("date"), str) else ""
        if date:
            block += f"\nPublished: {date}"
        if excerpt:
            block += f"\n\n{excerpt}"
        elif snippet:
            # fallback to ddgs snippet if fetch failed
            block += f"\n\n{snippet}"

        sections.append(block)

    return "\n\n---\n\n".join(sections)