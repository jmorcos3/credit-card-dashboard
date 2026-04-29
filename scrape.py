"""Weekly scraper: pulls credit card offer signals from RSS feeds.

Filters for high-signal keywords (increased offer, all-time high, fee increase,
new card, refresh, etc) and writes offers.json for dashboard consumption.
"""
import feedparser
import json
import re
from datetime import datetime, timezone

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"

FEEDS = [
    ("Doctor of Credit", "https://www.doctorofcredit.com/feed/"),
    ("The Points Guy", "https://thepointsguy.com/feed/"),
    ("Frequent Miler", "https://frequentmiler.com/feed/"),
    ("View from the Wing", "https://viewfromthewing.com/feed/"),
    ("One Mile at a Time", "https://onemileatatime.com/feed/"),
]

# Signal keywords — case-insensitive
HIGH_SIGNAL = [
    r"\ball[- ]time high\b",
    r"\bincreased (offer|bonus|sub)\b",
    r"\bbest[- ]ever\b",
    r"\bnew (card|offer|sub|sign[- ]up bonus)\b",
    r"\brefresh(ed|ing)?\b",
    r"\bfee (increase|hike)\b",
    r"\b(welcome|sign[- ]up) bonus\b",
    r"\b\d{2,3}[k,]?\s*(point|mile|bonvoy|membership)",
    r"\bgrandfathered?\b",
    r"\b75[k,]?\s*\+",
    r"\b100[k,]?\s*\+",
    r"\b150[k,]?\s*\+",
    r"\b175[k,]?\s*\+",
    r"\b200[k,]?\s*\+",
]

# Cards user cares about (Marriott, United, Chase, Amex personal, Bilt)
RELEVANT_CARDS = [
    r"\bmarriott\b",
    r"\bbonvoy\b",
    r"\bunited\b",
    r"\bchase\s+sapphire\b",
    r"\bsapphire (preferred|reserve)\b",
    r"\bcsp\b", r"\bcsr\b",
    r"\bamex\b",
    r"\bamerican express\b",
    r"\bplatinum card\b",
    r"\bgold card\b",
    r"\bbilt\b",
    r"\bgreen card\b",
]

# Exclusions (irrelevant noise)
EXCLUDE = [
    r"\bbusiness\b",  # user has no business
    r"\bink\b",  # Chase Ink = business
    r"\bbiz\b",
    r"\bhyatt\b",  # not user's hotel chain
    r"\bdelta skymiles\b",
    r"\bcapital one\b",
    r"\bcitibank|citi premier\b",
    r"\bbank of america|bofa\b",
    r"\bdiscover\b",
    r"\bwells fargo\b",
    r"\bvirgin atlantic\b",  # transfer partner only, not card
    r"\bcard counting\b",  # gambling not credit cards
    r"\batc\b|air traffic",
    r"\bhilton honors\b",  # user not in Hilton ecosystem
    r"\biceland|fiji|qatar\b",  # geo-irrelevant flight stories
]

high_re = re.compile("|".join(HIGH_SIGNAL), re.IGNORECASE)
relevant_re = re.compile("|".join(RELEVANT_CARDS), re.IGNORECASE)
exclude_re = re.compile("|".join(EXCLUDE), re.IGNORECASE)


CARD_CONTEXT = re.compile(
    r"\b(card|bonus|sub|sign[- ]up|offer|annual fee|points|miles|"
    r"application|approve|welcome|transfer|statement credit|referral|"
    r"expires|limited[- ]time|points offer|miles offer|free night)\b",
    re.IGNORECASE,
)


def score(title, summary):
    """Score 0-10. Requires relevant card + card context. High-signal boosts."""
    text = f"{title} {summary}"
    if exclude_re.search(text):
        return 0
    if not relevant_re.search(text):
        return 0
    if not CARD_CONTEXT.search(text):
        return 0
    # Title relevance counts more
    title_card = bool(relevant_re.search(title))
    title_signal = bool(high_re.search(title))
    body_signal = len(high_re.findall(summary))
    base = 4 if title_card else 2
    base += 3 if title_signal else 0
    base += min(3, body_signal)
    return min(10, base)


def clean_html(s):
    return re.sub(r"<[^>]+>", "", s or "").strip()


def fetch_feed(name, url):
    items = []
    try:
        feed = feedparser.parse(url, request_headers={"User-Agent": UA})
        for entry in feed.entries[:30]:  # last 30 posts per feed
            title = entry.get("title", "")
            summary = clean_html(entry.get("summary", ""))[:400]
            link = entry.get("link", "")
            published = entry.get("published_parsed") or entry.get("updated_parsed")
            published_iso = (
                datetime(*published[:6], tzinfo=timezone.utc).isoformat()
                if published else None
            )
            s = score(title, summary)
            if s == 0:
                continue
            items.append({
                "source": name,
                "title": title,
                "summary": summary,
                "link": link,
                "published": published_iso,
                "score": s,
            })
    except Exception as e:
        print(f"[{name}] failed: {e}")
    return items


def main():
    all_items = []
    for name, url in FEEDS:
        items = fetch_feed(name, url)
        print(f"[{name}] {len(items)} relevant items")
        all_items.extend(items)

    # Dedup by title (case-insensitive, fuzzy)
    seen = set()
    unique = []
    for item in sorted(all_items, key=lambda x: -x["score"]):
        key = re.sub(r"[^a-z0-9]", "", item["title"].lower())[:60]
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    # Sort by score desc, then date desc
    unique.sort(key=lambda x: (-x["score"], x.get("published") or ""), reverse=False)
    unique.sort(key=lambda x: -x["score"])

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "feed_count": len(FEEDS),
        "item_count": len(unique),
        "items": unique[:25],  # top 25
    }

    with open("offers.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"Wrote {len(unique[:25])} items to offers.json")


if __name__ == "__main__":
    main()
