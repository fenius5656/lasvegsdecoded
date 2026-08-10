#!/usr/bin/env python3
"""
Vegas Decoded — Automated blog-post generator
==============================================
For each new long-form video that doesn't yet have a post, this:
  1. Finds the matching episode script in Google Drive (service account).
  2. Reads the script text (incl. its verification log of sourced facts).
  3. Calls the Claude API to write a rich, brand-styled post from those facts.
  4. Renders the branded HTML page + adds an entry to data/posts.json.

Runs in GitHub Actions (see .github/workflows/auto-blog.yml). The workflow
opens a Pull Request with whatever this script creates — a human merges to publish.

Required environment:
  ANTHROPIC_API_KEY   - Claude API key
  GDRIVE_SA_KEY       - Google service-account JSON (the whole file, as a string)
Optional:
  VD_MODEL            - Claude model id (default: claude-opus-5; set claude-sonnet-5 to cut cost)
  VD_MAX_POSTS        - max posts to generate per run (default: 2)
  GDRIVE_FOLDER_ID    - restrict the Drive search to this folder (recommended)
"""

import json
import os
import re
import sys
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VIDEOS = ROOT / "data" / "videos.json"
POSTS = ROOT / "data" / "posts.json"
POSTS_DIR = ROOT / "posts"

MODEL = os.environ.get("VD_MODEL", "claude-opus-5").strip()
MAX_POSTS = int(os.environ.get("VD_MAX_POSTS", "2"))
FOLDER_ID = os.environ.get("GDRIVE_FOLDER_ID", "").strip()

STOPWORDS = {
    "the", "a", "an", "is", "in", "on", "of", "to", "for", "and", "or", "las",
    "vegas", "your", "you", "it", "this", "that", "was", "are", "how", "why",
    "what", "with", "from", "just", "got", "has", "shorts", "short",
}


# ----------------------------- Google Drive -----------------------------

def drive_service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    raw = os.environ.get("GDRIVE_SA_KEY", "").strip()
    if not raw:
        print("ERROR: GDRIVE_SA_KEY not set.", file=sys.stderr)
        sys.exit(1)
    info = json.loads(raw)
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/drive.readonly"]
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def find_script_file(svc, video_title):
    """Search Drive for the long-form episode script matching a video title."""
    clean = re.sub(r"#\w+", " ", video_title)
    words = [w for w in re.findall(r"[A-Za-z0-9']+", clean)
             if len(w) > 3 and w.lower() not in STOPWORDS]
    if not words:
        return None
    # Try progressively looser keyword sets.
    for kws in (words[:3], words[:2], words[:1]):
        clauses = " and ".join(
            f"fullText contains '{w.replace(chr(39), chr(92)+chr(39))}'" for w in kws
        )
        q = (f"({clauses}) and trashed=false and ("
             "mimeType='application/vnd.openxmlformats-officedocument.wordprocessingml.document' "
             "or mimeType='application/vnd.google-apps.document')")
        if FOLDER_ID:
            q += f" and '{FOLDER_ID}' in parents"
        try:
            res = svc.files().list(
                q=q, fields="files(id,name,mimeType)", pageSize=25,
                supportsAllDrives=True, includeItemsFromAllDrives=True,
            ).execute()
        except Exception as e:  # noqa: BLE001
            print(f"  Drive search error: {e}", file=sys.stderr)
            return None
        files = res.get("files", [])
        # Prefer the long-form script doc over shorts/other docs.
        def score(f):
            n = f["name"].lower()
            s = 0
            if "script" in n:
                s += 2
            if "long" in n:
                s += 3
            if "short" in n:
                s -= 3
            return s
        files.sort(key=score, reverse=True)
        if files and score(files[0]) > -3:
            return files[0]
    return None


def read_drive_text(svc, file_meta):
    """Return the plain text of a Drive doc (Google Doc export or .docx download)."""
    fid, mime = file_meta["id"], file_meta["mimeType"]
    if mime == "application/vnd.google-apps.document":
        data = svc.files().export(fileId=fid, mimeType="text/plain").execute()
        return data.decode("utf-8", "ignore") if isinstance(data, bytes) else str(data)
    # .docx download + parse
    from googleapiclient.http import MediaIoBaseDownload
    import docx  # python-docx

    buf = BytesIO()
    req = svc.files().get_media(fileId=fid, supportsAllDrives=True)
    dl = MediaIoBaseDownload(buf, req)
    done = False
    while not done:
        _, done = dl.next_chunk()
    buf.seek(0)
    document = docx.Document(buf)
    return "\n".join(p.text for p in document.paragraphs)


# ----------------------------- Claude -----------------------------

POST_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "title": {"type": "string"},
        "slug": {"type": "string"},
        "excerpt": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "readTime": {"type": "string"},
        "keyFacts": {"type": "array", "items": {"type": "string"}},
        "introHtml": {"type": "string"},
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "heading": {"type": "string"},
                    "html": {"type": "string"},
                },
                "required": ["heading", "html"],
            },
        },
        "tip": {"type": "string"},
        "verdictType": {"type": "string", "enum": ["worth-it", "skip-it", "none"]},
        "verdictLabel": {"type": "string"},
        "verdictText": {"type": "string"},
        "faqs": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"q": {"type": "string"}, "a": {"type": "string"}},
                "required": ["q", "a"],
            },
        },
    },
    "required": ["title", "slug", "excerpt", "tags", "readTime", "keyFacts",
                 "introHtml", "sections", "tip", "verdictType", "verdictLabel",
                 "verdictText", "faqs"],
}

SYSTEM = """You write blog posts for "Vegas Decoded", a Las Vegas YouTube channel whose brand is "The real stories. The real Vegas." — honest, no-hype, value-focused coverage of hotels, casinos, food, shows and deals.

You will be given the channel's own episode script, which includes a VERIFICATION LOG of fact-checked, sourced claims. Turn it into a rich 1,000–1,400 word blog post.

STRICT RULES:
- Use ONLY facts present in the provided script. Prefer numbers/claims from the VERIFICATION LOG. Never invent prices, dates, ratings, or names. If unsure, omit it.
- Tone: direct, confident, a little witty; short paragraphs; no fluff or clickbait.
- Every dollar figure, rating, and date must trace to the script.

OUTPUT (structured JSON):
- title: punchy, <70 chars, no hashtags.
- slug: lowercase-with-dashes, no dates.
- excerpt: one-sentence teaser (<160 chars).
- tags: 2-3 short topic tags (e.g. "Hotels", "The Strip", "News").
- readTime: like "4 min read".
- keyFacts: 3-5 short bullet strings for a TL;DR box (the most important verified facts).
- introHtml: 2 short <p> paragraphs that hook the reader with the real takeaway.
- sections: 3-5 sections, each a heading + html. html may use only these tags: <p>, <strong>, <em>, <ul>, <ol>, <li>, <blockquote>, <a href>. No headings inside html.
- tip: one actionable insider tip, <25 words (plain text, no tags).
- verdictType: "worth-it", "skip-it", or "none" (use none for pure news/history).
- verdictLabel: e.g. "WORTH IT", "SKIP IT", "WORTH A LOOK" (empty if none).
- verdictText: one sentence explaining the verdict (empty if none).
- faqs: 3-4 short question/answer pairs a traveler would Google (answers 1-2 sentences, from the script)."""


def generate(script_text, video_title):
    import anthropic

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
    script_text = script_text[:24000]
    user = (f"VIDEO TITLE: {video_title}\n\n"
            f"EPISODE SCRIPT (source of truth — includes the verification log):\n\n{script_text}")
    resp = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        system=SYSTEM,
        messages=[{"role": "user", "content": user}],
        output_config={"format": {"type": "json_schema", "schema": POST_SCHEMA}},
    )
    if resp.stop_reason == "refusal":
        print("  Claude refused; skipping.", file=sys.stderr)
        return None
    text = next((b.text for b in resp.content if b.type == "text"), "")
    return json.loads(text)


# ----------------------------- Rendering -----------------------------

def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def render_page(data, video_id, date_iso):
    tags = "".join(f'<span class="tag">{esc(t)}</span>' for t in data["tags"][:3])
    facts = "".join(f"<li>{esc(f)}</li>" for f in data["keyFacts"])
    sections = ""
    for s in data["sections"]:
        sections += f'\n      <h2>{esc(s["heading"])}</h2>\n      {s["html"]}\n'
    tip = ""
    if data.get("tip"):
        tip = (f'\n      <div class="vd-tip" style="margin:28px 0;">\n'
               f'        <div class="vd-tip-icon">TIP</div>\n'
               f'        <div class="vd-tip-text">{esc(data["tip"])}</div>\n      </div>\n')
    verdict = ""
    if data.get("verdictType") in ("worth-it", "skip-it") and data.get("verdictLabel"):
        icon = "✓" if data["verdictType"] == "worth-it" else "✕"
        verdict = (f'\n      <h2>The verdict</h2>\n      <p>{esc(data.get("verdictText",""))}</p>\n'
                   f'      <p><span class="vd-verdict {data["verdictType"]}">{icon} {esc(data["verdictLabel"])}</span></p>\n')
    faqs = ""
    if data.get("faqs"):
        items = "".join(
            f'\n        <div class="faq-item">\n          <div class="faq-q">{esc(f["q"])}</div>\n'
            f'          <div class="faq-a">{esc(f["a"])}</div>\n        </div>' for f in data["faqs"])
        faqs = (f'\n      <h2>FAQ</h2>\n      <div class="faq">{items}\n      </div>\n')
    desc = esc(data["excerpt"])
    title = esc(data["title"])
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} — Vegas Decoded</title>
<meta name="description" content="{desc}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:type" content="article">
<meta property="og:image" content="https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=DM+Sans:wght@300;400;500;600;700&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<link rel="stylesheet" href="../assets/css/style.css">
</head>
<body>

<nav class="nav">
  <div class="nav-inner">
    <a class="brand" href="../index.html">VEGAS <span>DECODED</span></a>
    <button class="nav-toggle" aria-label="Menu">☰</button>
    <div class="nav-links">
      <a href="../index.html">Home</a>
      <a href="../videos.html">Videos</a>
      <a href="../posts.html" class="active">Posts</a>
      <a class="nav-cta" data-channel-link href="#" target="_blank" rel="noopener">Subscribe</a>
    </div>
  </div>
</nav>

<article class="article">
  <div class="container article-wrap">

    <div class="article-header">
      <div class="post-tags">{tags}</div>
      <h1>{title}</h1>
      <div class="article-meta">
        <span>{date_iso}</span>
        <span>·</span>
        <span>{esc(data["readTime"])}</span>
      </div>
    </div>

    <div class="article-body">
      {data["introHtml"]}

      <div class="tldr-box">
        <div class="tldr-label">The Quick Answer</div>
        <ul>{facts}</ul>
      </div>

      <div class="article-embed">
        <iframe src="https://www.youtube.com/embed/{video_id}" title="{title}"
                allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                allowfullscreen loading="lazy"></iframe>
      </div>
{sections}{tip}{verdict}{faqs}
      <p style="color:var(--muted);font-size:14px;margin-top:32px;">Facts drawn from the Vegas Decoded episode and verified at time of writing; prices and details can change. Watch the full episode on the <a data-channel-link href="#" target="_blank" rel="noopener">Vegas Decoded channel</a>.</p>
    </div>

  </div>
</article>

<footer class="footer">
  <div class="footer-inner">
    <div class="footer-brand">
      <div class="brand">VEGAS <span>DECODED</span></div>
      <p>The real stories. The real Vegas.</p>
    </div>
    <div class="footer-links">
      <div class="footer-col">
        <h4>Explore</h4>
        <a href="../index.html">Home</a>
        <a href="../videos.html">Videos</a>
        <a href="../posts.html">Posts</a>
      </div>
      <div class="footer-col">
        <h4>Follow</h4>
        <a data-channel-link href="#" target="_blank" rel="noopener">YouTube</a>
      </div>
    </div>
  </div>
  <div class="footer-bottom">
    <span>© <span id="year"></span> Vegas Decoded</span>
    <span>Built lean. Hosted free.</span>
  </div>
</footer>

<script>document.getElementById('year').textContent = new Date().getFullYear();</script>
<script src="../assets/js/config.js"></script>
<script src="../assets/js/main.js"></script>
</body>
</html>
"""


# ----------------------------- Main -----------------------------

def is_short(v):
    return bool(re.search(r"#shorts?\b", v.get("title", ""), re.I))


def slugify(s):
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s[:70] or "post"


_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def display_date(iso):
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", iso or "")
    if not m:
        return iso or ""
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return f"{_MONTHS[mo - 1]} {d}, {y}"


def main():
    videos = json.loads(VIDEOS.read_text(encoding="utf-8")).get("videos", [])
    posts_data = json.loads(POSTS.read_text(encoding="utf-8"))
    posts = posts_data.get("posts", [])
    have = {p.get("videoId") for p in posts if p.get("videoId")}
    have_slugs = {p["slug"] for p in posts}

    todo = [v for v in videos if not is_short(v) and v["id"] not in have]
    if not todo:
        print("No new long-form videos need a post.")
        return 0

    svc = drive_service()
    created = 0
    for v in todo:
        if created >= MAX_POSTS:
            break
        title = v["title"]
        print(f"→ {title}")
        fm = find_script_file(svc, title)
        if not fm:
            print("  No matching Drive script found; skipping.")
            continue
        print(f"  Script: {fm['name']}")
        try:
            script_text = read_drive_text(svc, fm)
        except Exception as e:  # noqa: BLE001
            print(f"  Could not read script: {e}", file=sys.stderr)
            continue
        if len(script_text) < 400:
            print("  Script too short; skipping.")
            continue
        data = generate(script_text, title)
        if not data:
            continue
        slug = slugify(data.get("slug") or data["title"])
        if slug in have_slugs:
            slug = f"{slug}-{v['id'][:6].lower()}"
        date_iso = (v.get("published") or "")[:10]
        html = render_page(data, v["id"], display_date(date_iso))
        (POSTS_DIR / f"{slug}.html").write_text(html, encoding="utf-8")
        posts.insert(0, {
            "slug": slug,
            "title": data["title"],
            "excerpt": data["excerpt"],
            "date": date_iso,
            "readTime": data["readTime"],
            "tags": data["tags"][:3],
            "cover": f"https://i.ytimg.com/vi/{v['id']}/maxresdefault.jpg",
            "videoId": v["id"],
        })
        have_slugs.add(slug)
        created += 1
        print(f"  Created posts/{slug}.html")

    if created:
        POSTS.write_text(json.dumps(posts_data, indent=2, ensure_ascii=False) + "\n",
                         encoding="utf-8")
        print(f"Done. Created {created} post(s).")
    else:
        print("Done. No posts created this run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
