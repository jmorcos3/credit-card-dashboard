"""Weekly scraper: pulls credit card offer signals from RSS feeds + Reddit.

Tiered relevance:
  TIER 1 (cards/programs user actively uses): big score boost
  TIER 2 (same issuers, different products): allowed at reduced weight
  OTHER (Citi/Cap One/BoA/etc): only if extremely compelling (score >= 8)
  BUSINESS cards: hard exclude

Also writes history/<YYYY-MM-DD>.json snapshot for trend tracking.
"""
import feedparser
import json
import os
import re
import urllib.request
from datetime import datetime, timezone

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"

FEEDS = [
    ("Doctor of Credit", "https://www.doctorofcredit.com/feed/"),
    ("The Points Guy", "https://thepointsguy.com/feed/"),
    ("Frequent Miler", "https://frequentmiler.com/feed/"),
    ("View from the Wing", "https://viewfromthewing.com/feed/"),
    ("One Mile at a Time", "https://onemileatatime.com/feed/"),
    ("r/churning", "https://www.reddit.com/r/churning/.rss?limit=50"),
]

# TIER 1 — user actively uses these cards / programs
TIER1 = re.compile(
    r"\b(marriott|bonvoy|brilliant|bevy|"
    r"united|mileageplus|polaris|"
    r"american airlines|aadvantage|"
    r"amex gold|gold card|"
    r"amex platinum|platinum card|"
    r"chase sapphire|sapphire (preferred|reserve)|csp|csr|"
    r"freedom unlimited|cfu|"
    r"bilt|"
    r"membership rewards|ultimate rewards)\b",
    re.IGNORECASE,
)

# TIER 2 — same issuers, different personal products user might consider
TIER2 = re.compile(
    r"\b(amex green|green card|"
    r"chase freedom flex|cff|"
    r"chase aeroplan|"
    r"hilton aspire|"  # Amex Hilton (user not in but Amex)
    r"delta amex|amex delta|"  # Amex Delta personal
    r"southwest)\b",  # transfer relevance
    re.IGNORECASE,
)

# Hard exclude — business cards (user has no business)
BUSINESS = re.compile(
    r"\b(business|biz|ink (preferred|cash|unlimited|premier|business)|"
    r"amex business|amex biz|"
    r"spark (cash|miles|business)|"
    r"venture x business|"
    r"corporate card|corporate program|"
    r"chase ink|"
    r"capital one spark)\b",
    re.IGNORECASE,
)

# Other exclusions (not user-relevant)
OTHER_EXCLUDE = re.compile(
    r"\b(hyatt|"
    r"card counting|atc|air traffic|"
    r"hilton honors|"  # not in ecosystem (but Aspire still tier-2)
    r"iceland|fiji|qatar airways|"
    r"sky high travel review)\b",
    re.IGNORECASE,
)

# Card context — must have one of these terms
CARD_CONTEXT = re.compile(
    r"\b(card|bonus|sub|sign[- ]up|offer|annual fee|points|miles|"
    r"application|approve|welcome|transfer|statement credit|referral|"
    r"expires|limited[- ]time|free night|status|elite|companion pass)\b",
    re.IGNORECASE,
)

# High-signal patterns
HIGH_SIGNAL = re.compile(
    r"\ball[- ]time high\b|"
    r"\bincreased (offer|bonus|sub)\b|"
    r"\bbest[- ]ever\b|"
    r"\brefresh(ed|ing)?\b|"
    r"\bfee (increase|hike|change)\b|"
    r"\bgrandfathered?\b|"
    r"\b(welcome|sign[- ]up) bonus\b|"
    r"\b(75|100|125|150|175|200|250)[k,]?\s*(point|mile|bonvoy)|"
    r"\bnew (card|offer|sub|sign[- ]up bonus)\b|"
    r"\btransfer bonus\b",
    re.IGNORECASE,
)


def clean_html(s):
    return re.sub(r"<[^>]+>", "", s or "").strip()


def score(title, summary):
    """Tiered scoring. Business -> 0. Other excluded -> 0.
    TIER1 -> base 5, +signal hits.
    TIER2 -> base 3, +signal hits.
    Neither -> only if signal hits >= 3 ('extremely compelling')."""
    text = f"{title} {summary}"
    if BUSINESS.search(text):
        return 0, "business"
    if OTHER_EXCLUDE.search(text):
        return 0, "excluded"
    if not CARD_CONTEXT.search(text):
        return 0, "no-context"

    title_signal = bool(HIGH_SIGNAL.search(title))
    body_signals = len(HIGH_SIGNAL.findall(summary))
    total_signals = (1 if title_signal else 0) + body_signals

    t1 = bool(TIER1.search(text))
    t2 = bool(TIER2.search(text))

    if t1:
        base = 5
        # Extra boost for TIER1 in title
        if TIER1.search(title):
            base += 2
        return min(10, base + total_signals), "tier1"
    if t2:
        return min(8, 3 + total_signals), "tier2"

    # Other cards only if extremely compelling
    if total_signals >= 3:
        return min(7, 1 + total_signals), "other-compelling"
    return 0, "other-skipped"


def fetch_feed(name, url):
    items = []
    try:
        feed = feedparser.parse(url, request_headers={"User-Agent": UA})
        for entry in feed.entries[:40]:
            title = entry.get("title", "")
            summary = clean_html(entry.get("summary", ""))[:500]
            link = entry.get("link", "")
            published = entry.get("published_parsed") or entry.get("updated_parsed")
            published_iso = (
                datetime(*published[:6], tzinfo=timezone.utc).isoformat()
                if published else None
            )
            s, tier = score(title, summary)
            if s == 0:
                continue
            items.append({
                "source": name,
                "title": title,
                "summary": summary[:300],
                "link": link,
                "published": published_iso,
                "score": s,
                "tier": tier,
            })
    except Exception as e:
        print(f"[{name}] failed: {e}")
    return items


def llm_summarize(items):
    """One-line summary per item via Claude. Skips if no API key."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key or not items:
        return items
    try:
        import json as _json
        for item in items:
            prompt = (
                "Summarize this credit card offer in ONE short sentence (under 20 words). "
                "Focus on actionable detail (bonus amount, deadline, fee). No fluff.\n\n"
                f"Title: {item['title']}\nSummary: {item['summary'][:300]}\n\nOne sentence:"
            )
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                data=_json.dumps({
                    "model": "claude-haiku-4-5",
                    "max_tokens": 80,
                    "messages": [{"role": "user", "content": prompt}],
                }).encode(),
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = _json.loads(resp.read())
                item["tldr"] = data["content"][0]["text"].strip()
    except Exception as e:
        print(f"LLM summary failed: {e}")
    return items


def compare_to_last_week(current):
    """Mark items as new vs returning by comparing to most recent prior snapshot."""
    if not os.path.isdir("history"):
        return current
    snapshots = sorted(f for f in os.listdir("history") if f.endswith(".json"))
    if len(snapshots) < 1:
        return current
    today_file = datetime.now(timezone.utc).strftime("%Y-%m-%d") + ".json"
    prior = [s for s in snapshots if s != today_file]
    if not prior:
        return current
    try:
        with open(f"history/{prior[-1]}", encoding="utf-8") as f:
            last = json.load(f)
        last_keys = {re.sub(r"[^a-z0-9]", "", i["title"].lower())[:60] for i in last.get("items", [])}
        for item in current:
            key = re.sub(r"[^a-z0-9]", "", item["title"].lower())[:60]
            item["is_new"] = key not in last_keys
    except Exception as e:
        print(f"Compare failed: {e}")
    return current


def main():
    all_items = []
    for name, url in FEEDS:
        items = fetch_feed(name, url)
        print(f"[{name}] {len(items)} items")
        all_items.extend(items)

    # Dedup by fuzzy title
    seen = set()
    unique = []
    for item in sorted(all_items, key=lambda x: -x["score"]):
        key = re.sub(r"[^a-z0-9]", "", item["title"].lower())[:60]
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    unique.sort(key=lambda x: -x["score"])
    top = unique[:30]

    # Mark new vs returning vs prior week
    top = compare_to_last_week(top)

    # LLM summarize top 10 only (cost control)
    top[:10] = llm_summarize(top[:10])

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "feed_count": len(FEEDS),
        "item_count": len(top),
        "items": top,
    }

    with open("offers.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    # Snapshot for history
    os.makedirs("history", exist_ok=True)
    snapshot = f"history/{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.json"
    with open(snapshot, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    # Write high-signal items for issue digest
    high = [i for i in unique if i["score"] >= 7]
    with open("high_signal.json", "w", encoding="utf-8") as f:
        json.dump({"items": high}, f, indent=2)

    print(f"Wrote {len(unique[:30])} items, {len(high)} high-signal")


if __name__ == "__main__":
    main()
