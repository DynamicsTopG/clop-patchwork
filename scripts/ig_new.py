"""Find @clop_patchwork posts not yet on the website and prep them as cards.

Compares scripts/clop_posts.json (refresh it first with ig_fetch.py) against the
Instagram links in index.html. For each missing post it downloads the image to
img/post-NN.jpg (next free number) and prints the full caption, ready for someone
(or Claude) to write the card copy + English translation into index.html.

Run:  python scripts/ig_fetch.py && python scripts/ig_new.py
"""
import json, os, re, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POSTS = os.path.join(ROOT, "scripts", "clop_posts.json")
INDEX = os.path.join(ROOT, "index.html")
IMG = os.path.join(ROOT, "img")

def main():
    with open(POSTS, encoding="utf-8") as f:
        posts = json.load(f)
    with open(INDEX, encoding="utf-8") as f:
        html = f.read()

    on_site = set(re.findall(r"instagram\.com/p/([^/\"]+)", html))
    missing = [p for p in posts if p["shortcode"] not in on_site]
    if not missing:
        print("Site is up to date: no new posts.")
        return

    nums = [int(m) for m in re.findall(r"post-(\d+)\.jpg", " ".join(os.listdir(IMG)))]
    next_num = max(nums, default=0) + 1

    for p in missing:
        img_name = f"post-{next_num:02d}.jpg"
        url = p.get("og_image") or p.get("image") or p.get("image_url") or p.get("thumbnail")
        status = "no image URL"
        if url:
            try:
                req = urllib.request.Request(url, headers={"user-agent": "Mozilla/5.0"})
                data = urllib.request.urlopen(req, timeout=30).read()
                if data[:3] == b"\xff\xd8\xff":
                    with open(os.path.join(IMG, img_name), "wb") as f:
                        f.write(data)
                    status = f"image saved as img/{img_name}"
                    next_num += 1
                else:
                    status = "download was not a JPEG (CDN URL expired? re-run ig_fetch.py)"
            except Exception as e:
                status = f"image download failed: {e}"

        caption = p.get("og_title") or p.get("caption") or ""
        print("=" * 70)
        print("NEW POST:", p["url"])
        print("IMAGE:", status)
        print("CAPTION:")
        print(caption)
        print()

    print(f"{len(missing)} new post(s). Next: write the card(s) into index.html")
    print("(article.card block + name-N/mat-N entries in the EN dictionary).")

if __name__ == "__main__":
    main()
