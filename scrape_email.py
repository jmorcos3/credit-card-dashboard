"""Gmail scraper: extract TPG / DoC / FM newsletter offers from inbox.

Uses Gmail API via OAuth2 refresh token. Three secrets required:
  GMAIL_CLIENT_ID
  GMAIL_CLIENT_SECRET
  GMAIL_REFRESH_TOKEN

Run gen_gmail_token.py locally once to mint the refresh token.

Outputs offers_email.json — merged with offers.json by dashboard.
"""
import base64
import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email import message_from_bytes
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser

# Senders to scan (case-insensitive substring match in From header)
SENDERS = [
    "thepointsguy.com",
    "doctorofcredit.com",
    "frequentmiler.com",
    "viewfromthewing.com",
    "onemileatatime.com",
    "boardingarea.com",
    "milestomemories.com",
]

# Same tier system as scrape.py
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

BUSINESS = re.compile(
    r"\b(business|biz|ink (preferred|cash|unlimited|premier|business)|"
    r"amex business|amex biz|"
    r"spark (cash|miles|business)|"
    r"venture x business|"
    r"corporate card|chase ink|capital one spark)\b",
    re.IGNORECASE,
)

EXCLUDE = re.compile(
    r"\b(hyatt|card counting|atc|air traffic|hilton honors|"
    r"iceland|fiji|qatar airways)\b",
    re.IGNORECASE,
)

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
    r"\btransfer bonus\b|"
    r"\blimited[- ]time\b",
    re.IGNORECASE,
)


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "head"}:
            self._skip = True

    def handle_endtag(self, tag):
        if tag in {"script", "style", "head"}:
            self._skip = False

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)

    def text(self):
        return re.sub(r"\s+", " ", " ".join(self.parts)).strip()


def get_access_token():
    """Exchange refresh token for access token."""
    client_id = os.environ["GMAIL_CLIENT_ID"]
    client_secret = os.environ["GMAIL_CLIENT_SECRET"]
    refresh_token = os.environ["GMAIL_REFRESH_TOKEN"]
    data = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())["access_token"]


def gmail_get(path, token, **params):
    url = "https://gmail.googleapis.com/gmail/v1/users/me" + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


def b64decode(s):
    if not s:
        return b""
    pad = (-len(s)) % 4
    return base64.urlsafe_b64decode(s + "=" * pad)


def extract_body(payload):
    """Recursively pull text/html or text/plain content."""
    if payload.get("mimeType") in {"text/plain", "text/html"}:
        data = payload.get("body", {}).get("data")
        if data:
            return b64decode(data).decode("utf-8", errors="ignore")
    for part in payload.get("parts", []) or []:
        body = extract_body(part)
        if body:
            return body
    return ""


def score(title, body):
    text = f"{title} {body}"
    if BUSINESS.search(text):
        return 0
    if EXCLUDE.search(text):
        return 0
    if not TIER1.search(text):
        return 0
    signals = len(HIGH_SIGNAL.findall(text))
    if signals == 0:
        return 0
    base = 6 if TIER1.search(title) else 4
    base += min(4, signals)
    return min(10, base)


def fetch_emails():
    token = get_access_token()
    # Build query: from any sender, last 14 days
    from_clause = " OR ".join(f"from:{s}" for s in SENDERS)
    query = f"({from_clause}) newer_than:14d"
    listing = gmail_get("/messages", token, q=query, maxResults=50)
    messages = listing.get("messages", [])
    items = []
    for m in messages:
        try:
            msg = gmail_get(f"/messages/{m['id']}", token, format="full")
            headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
            subject = headers.get("Subject", "")
            sender = headers.get("From", "")
            date_str = headers.get("Date", "")
            try:
                published_iso = parsedate_to_datetime(date_str).astimezone(timezone.utc).isoformat()
            except Exception:
                published_iso = None

            body_raw = extract_body(msg["payload"])
            if "<" in body_raw and ">" in body_raw:
                parser = TextExtractor()
                parser.feed(body_raw)
                body_text = parser.text()
            else:
                body_text = body_raw

            body_text = body_text[:1500]
            s = score(subject, body_text)
            if s == 0:
                continue

            # Extract source from sender
            source = "Email"
            for sender_dom in SENDERS:
                if sender_dom.lower() in sender.lower():
                    source = sender_dom.split(".")[0].title()
                    if "thepointsguy" in sender_dom:
                        source = "TPG Newsletter"
                    elif "doctorofcredit" in sender_dom:
                        source = "DoC Newsletter"
                    elif "frequentmiler" in sender_dom:
                        source = "FM Newsletter"
                    break

            # Try to extract first prominent link
            link_match = re.search(r'https?://[^\s"\'<>)]+', body_raw)
            link = link_match.group(0) if link_match else ""

            items.append({
                "source": source,
                "title": subject,
                "summary": body_text[:300],
                "link": link,
                "published": published_iso,
                "score": s,
                "tier": "tier1",
                "from_email": True,
            })
        except Exception as e:
            print(f"Skip msg {m.get('id')}: {e}")
    return items


def main():
    if not all(os.environ.get(k) for k in ("GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN")):
        print("Gmail secrets missing — writing empty offers_email.json")
        with open("offers_email.json", "w", encoding="utf-8") as f:
            json.dump({"generated_at": datetime.now(timezone.utc).isoformat(), "items": []}, f, indent=2)
        return

    items = fetch_emails()
    # Dedup by fuzzy title
    seen = set()
    unique = []
    for it in sorted(items, key=lambda x: -x["score"]):
        key = re.sub(r"[^a-z0-9]", "", it["title"].lower())[:60]
        if key in seen:
            continue
        seen.add(key)
        unique.append(it)

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "item_count": len(unique),
        "items": unique[:20],
    }
    with open("offers_email.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"Wrote {len(unique[:20])} email offers")


if __name__ == "__main__":
    main()
