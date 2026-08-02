"""Import a Netscape cookies.txt (exported from the browser while logged into
Instagram) into an Instaloader session file, so posts can be downloaded without
a password. Run once; the saved session is reused afterwards.

Usage:
    python scripts/ig_import_cookies.py <path-to-cookies.txt> <ig-username>
"""
import sys
from http.cookiejar import MozillaCookieJar

import instaloader


def main():
    if len(sys.argv) < 3:
        print("Usage: python ig_import_cookies.py <cookies.txt> <ig-username>")
        sys.exit(1)

    cookies_path, username = sys.argv[1], sys.argv[2]

    jar = MozillaCookieJar(cookies_path)
    jar.load(ignore_discard=True, ignore_expires=True)
    ig_cookies = {c.name: c.value for c in jar if "instagram" in c.domain}

    if "sessionid" not in ig_cookies:
        print("ERROR: no Instagram 'sessionid' cookie found in", cookies_path)
        print("Make sure you exported cookies while logged in at instagram.com.")
        sys.exit(2)

    L = instaloader.Instaloader(quiet=True)
    L.context._session.cookies.update(ig_cookies)

    who = L.test_login()
    if not who:
        print("ERROR: cookies present but Instagram rejected the session.")
        print("Re-export a fresh cookies.txt while logged in and try again.")
        sys.exit(3)

    L.context.username = who
    L.save_session_to_file()  # -> %LOCALAPPDATA%\Instaloader\session-<who>
    print(f"OK: session saved for @{who}")


if __name__ == "__main__":
    main()
