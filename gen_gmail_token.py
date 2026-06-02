"""One-time helper: generate Gmail OAuth refresh token.

Uses the loopback-redirect flow (http://127.0.0.1:<port>). Google disabled
the old out-of-band ("oob") flow, so this spins up a tiny local web server,
opens the consent page, and catches the redirect automatically — no code to
copy and paste.

SETUP:
1. Go to https://console.cloud.google.com/
2. Create project (or use existing). Enable "Gmail API".
3. Google Auth Platform → Audience: publish the app to "In production"
   (Testing-mode refresh tokens expire after 7 days). Add the Gmail
   readonly scope: https://www.googleapis.com/auth/gmail.readonly
4. Clients → Create client → Application type: Desktop app.
   Save the Client ID + Client secret.
5. Run this script: python gen_gmail_token.py
   - Paste Client ID and Client Secret
   - Approve access in the browser window that opens
   - Refresh token is printed at the end
6. Update 3 GitHub secrets (Settings → Secrets and variables → Actions):
   - GMAIL_CLIENT_ID
   - GMAIL_CLIENT_SECRET
   - GMAIL_REFRESH_TOKEN
"""
import json
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

SCOPE = "https://www.googleapis.com/auth/gmail.readonly"

_result = {}


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        code = params.get("code", [None])[0]
        error = params.get("error", [None])[0]
        if code:
            _result["code"] = code
        if error:
            _result["error"] = error
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        msg = ("Authorization complete — you can close this tab and return to the terminal."
               if code else f"Authorization failed: {error}")
        self.wfile.write(f"<html><body><h2>{msg}</h2></body></html>".encode())

    def log_message(self, *args):
        pass  # keep the terminal clean


def main():
    print("Paste your OAuth Client ID:")
    client_id = input().strip()
    print("Paste your OAuth Client Secret:")
    client_secret = input().strip()

    server = HTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    redirect_uri = f"http://127.0.0.1:{port}/"

    auth_url = (
        "https://accounts.google.com/o/oauth2/v2/auth?"
        + urllib.parse.urlencode({
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": SCOPE,
            "access_type": "offline",
            "prompt": "consent",
        })
    )

    print("\nOpening your browser to approve access...")
    print("If it doesn't open automatically, paste this URL into your browser:\n")
    print(auth_url + "\n")
    webbrowser.open(auth_url)

    # Wait for the redirect from Google (ignore stray requests like /favicon.ico)
    while not _result.get("code") and not _result.get("error"):
        server.handle_request()
    server.server_close()

    if not _result.get("code"):
        print(f"\nAuthorization failed: {_result.get('error')}")
        return

    data = urllib.parse.urlencode({
        "code": _result["code"],
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data)
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read())

    refresh_token = result.get("refresh_token")
    if not refresh_token:
        print("\nNo refresh_token in the response:")
        print(json.dumps(result, indent=2))
        print("\nTip: revoke prior access at https://myaccount.google.com/permissions "
              "then run this again (refresh tokens are only returned on first consent).")
        return

    print("\n" + "=" * 60)
    print("SUCCESS — update these 3 secrets in GitHub:")
    print("=" * 60)
    print(f"GMAIL_CLIENT_ID:     {client_id}")
    print(f"GMAIL_CLIENT_SECRET: {client_secret}")
    print(f"GMAIL_REFRESH_TOKEN: {refresh_token}")
    print("=" * 60)
    print("\nGitHub repo → Settings → Secrets and variables → Actions → update each secret")


if __name__ == "__main__":
    main()
