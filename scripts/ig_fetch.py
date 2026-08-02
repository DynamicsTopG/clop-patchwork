"""Fetch recent @clop_patchwork posts (shortcode, date, caption, thumbnail) without login.

Drives a real headless Chrome via Playwright: the profile grid exposes the 12 most
recent posts anonymously, and each post page exposes its full caption in og: meta
tags. Output: scripts/clop_posts.json (newest first).

Setup (once):  python -m pip install playwright && python -m playwright install chromium
Run:           python scripts/ig_fetch.py

Note: posts beyond the newest 12 sit behind Instagram's login wall. To pull the
full archive, log in once in this browser profile:
    python scripts/ig_fetch.py --login   (opens a visible window; sign in, then close)
The profile persists at %USERPROFILE%\\.ig-playwright-profile, so later runs reuse it.
"""
import json, re, sys, os
from playwright.sync_api import sync_playwright

TARGET = "clop_patchwork"
PROFILE = os.path.join(os.path.expanduser("~"), ".ig-playwright-profile")
OUT = os.path.join(os.path.dirname(__file__), "clop_posts.json")

META_JS = """() => {
  const get = p => { const m = document.querySelector(`meta[property='${p}']`); return m ? m.content : null; };
  return { title: get('og:title'), image: get('og:image') };
}"""

def main():
    login_mode = "--login" in sys.argv
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            PROFILE, headless=not login_mode, channel="chromium",
            viewport={"width": 1280, "height": 2000},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        if login_mode:
            page.goto("https://www.instagram.com/accounts/login/")
            print("Sign in to Instagram in the window, then close it. The session is saved.")
            try:
                page.wait_for_event("close", timeout=600000)
            except Exception:
                pass
            ctx.close()
            return

        page.goto(f"https://www.instagram.com/{TARGET}/", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(6000)
        page.keyboard.press("Escape")

        # If logged in, scroll to load the full archive; anonymous gets the top 12.
        last = -1
        for _ in range(30):
            items = page.evaluate("""() =>
                [...document.querySelectorAll('a[href*="/p/"], a[href*="/reel/"]')].map(a => {
                  const img = a.querySelector('img');
                  return { href: a.getAttribute('href'), alt: img ? img.alt : null, src: img ? img.src : null };
                })""")
            if len(items) == last:
                break
            last = len(items)
            page.mouse.wheel(0, 3000)
            page.wait_for_timeout(1800)

        posts, seen = [], set()
        for it in items:
            m = re.search(r"/(?:p|reel)/([^/]+)/", it["href"] or "")
            if not m or m.group(1) in seen:
                continue
            seen.add(m.group(1))
            posts.append({"shortcode": m.group(1),
                          "url": f"https://www.instagram.com/p/{m.group(1)}/",
                          "alt": it["alt"], "thumbnail": it["src"]})
        print(f"grid: {len(posts)} posts found")

        for i, post in enumerate(posts):
            try:
                page.goto(post["url"], wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(2200)
                meta = page.evaluate(META_JS)
                title = meta["title"] or ""
                cap = re.search(r'[:：]\s*[""]([\s\S]*)[""]\s*$', title)
                post["caption"] = cap.group(1) if cap else title
                post["image"] = meta["image"]
                print(f"[{i+1}/{len(posts)}] {post['shortcode']} ok")
            except Exception as e:
                print(f"[{i+1}/{len(posts)}] {post['shortcode']} FAILED: {e}")
            page.wait_for_timeout(1300)

        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(posts, f, ensure_ascii=False, indent=1)
        print(f"saved {len(posts)} posts -> {OUT}")
        ctx.close()

if __name__ == "__main__":
    main()
