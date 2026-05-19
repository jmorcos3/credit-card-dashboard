"""One-time helper: generate Gmail OAuth refresh token.

SETUP:
1. Go to https://console.cloud.google.com/
2. Create project (or use existing). Enable "Gmail API".
3. APIs & Services → OAuth consent screen:
   - External user type, fill required fields
   - Add yourself as Test user
   - Scopes: add https://www.googleapis.com/auth/gmail.readonly
4. APIs & Services → Credentials → Create Credentials → OAuth Client ID:
   - Application type: Desktop app
   - Save the client_id + client_secret
5. Run this script: python gen_gmail_token.py
   - Paste client_id and client_secret
   - Visit URL printed
   - Approve, paste code back here
   - Refresh token printed at end
6. Add 3 GitHub secrets:
   - GMAIL_CLIENT_ID
   - GMAIL_CLIENT_SECRET
   - GMAIL_REFRESH_TOKEN
"""
import json
import urllib.parse
import urllib.request

SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
REDIRECT = "urn:ietf:wg:oauth:2.0:oob"


def main():
    print("Paste your OAuth Client ID:")
    client_id = input().strip()
    print("Paste your OAuth Client Secret:")
    client_secret = input().strip()

    auth_url = (
        "https://accounts.google.com/o/oauth2/v2/auth?"
        + urllib.parse.urlencode({
            "client_id": client_id,
            "redirect_uri": REDIRECT,
            "response_type": "code",
            "scope": SCOPE,
            "access_type": "offline",
            "prompt": "consent",
        })
    )

    print("\nOpen this URL in your browser, approve access, then paste the code:")
    print(auth_url)
    print("\nPaste authorization code:")
    code = input().strip()

    data = urllib.parse.urlencode({
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": REDIRECT,
        "grant_type": "authorization_code",
    }).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data)
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read())

    print("\n" + "=" * 60)
    print("SUCCESS — add these 3 secrets to GitHub:")
    print("=" * 60)
    print(f"GMAIL_CLIENT_ID:     {client_id}")
    print(f"GMAIL_CLIENT_SECRET: {client_secret}")
    print(f"GMAIL_REFRESH_TOKEN: {result['refresh_token']}")
    print("=" * 60)
    print("\nGitHub repo → Settings → Secrets and variables → Actions → New repository secret")


if __name__ == "__main__":
    main()
