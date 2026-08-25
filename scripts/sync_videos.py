#!/usr/bin/env python3
"""
Vegas Decoded — YouTube video sync
----------------------------------
Writes data/videos.json with the channel's videos.

Two modes:
  * If YOUTUBE_API_KEY is set  -> YouTube Data API v3: fetches the FULL catalog
    (every upload, paginated) with accurate publish dates. Recommended.
  * Otherwise                  -> RSS feed: only the latest 15 videos (a hard
    YouTube limit), MERGED into whatever is already in videos.json so nothing
    ever drops off the site.

Channel ID resolution: env VD_CHANNEL_ID, else "channelId" in data/videos.json.
A channel ID looks like UCxxxxxxxxxxxxxxxxxxxxxx.

Runs on GitHub Actions (.github/workflows/sync-videos.yml). No API key needed
for the RSS fallback; add YOUTUBE_API_KEY as a repo secret for the full list.
"""

import json
import os
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "videos.json"

FEED = "https://www.youtube.com/feeds/videos.xml?channel_id={cid}"
API = "https://www.googleapis.com/youtube/v3/playlistItems"
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
    "media": "http://search.yahoo.com/mrss/",
}
UA = {"User-Agent": "Mozilla/5.0 (compatible; VegasDecodedSync/2.0)"}
SKIP_TITLES = {"Private video", "Deleted video", "[Private video]", "[Deleted video]"}


def load_existing():
    if DATA.exists():
        try:
            return json.loads(DATA.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"updated": None, "channelId": "", "videos": []}


def resolve_channel_id(existing):
    return (os.environ.get("VD_CHANNEL_ID", "").strip()
            or (existing.get("channelId") or "").strip())


def thumb(vid):
    return f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"


# ---------------------- YouTube Data API (full catalog) ----------------------

def fetch_all_via_api(cid, key):
    """Fetch every video in the channel's uploads playlist. Raises on error."""
    uploads = "UU" + cid[2:]  # uploads playlist id = channel id with UC->UU
    videos, page = [], ""
    while True:
        params = {
            "part": "snippet,contentDetails",
            "playlistId": uploads,
            "maxResults": "50",
            "key": key,
        }
        if page:
            params["pageToken"] = page
        url = API + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if "error" in data:
            raise RuntimeError(data["error"])
        for it in data.get("items", []):
            sn = it.get("snippet", {})
            cd = it.get("contentDetails", {})
            vid = cd.get("videoId") or sn.get("resourceId", {}).get("videoId")
            title = (sn.get("title") or "").strip()
            if not vid or title in SKIP_TITLES:
                continue
            published = cd.get("videoPublishedAt") or sn.get("publishedAt") or ""
            videos.append({"id": vid, "title": title,
                           "published": published, "thumbnail": thumb(vid)})
        page = data.get("nextPageToken")
        if not page:
            break
    return videos


# ---------------------- RSS feed (latest 15, fallback) ----------------------

def fetch_feed(cid, attempts=3):
    url = FEED.format(cid=cid)
    last = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read()
        except Exception as e:  # noqa: BLE001
            last = e
            if i < attempts - 1:
                time.sleep(5 * (i + 1))
    raise last


def parse_feed(xml_bytes):
    root = ET.fromstring(xml_bytes)
    out = []
    for entry in root.findall("atom:entry", NS):
        vid = entry.findtext("yt:videoId", default="", namespaces=NS)
        title = entry.findtext("atom:title", default="", namespaces=NS).strip()
        published = entry.findtext("atom:published", default="", namespaces=NS)
        if vid:
            out.append({"id": vid, "title": title,
                        "published": published, "thumbnail": thumb(vid)})
    return out


# ------------------------------- Merge + write -------------------------------

def sort_key(v):
    return (v.get("published") or "")[:19]


def merge(existing, fresh):
    by_id = {v["id"]: v for v in existing if v.get("id")}
    for v in fresh:
        by_id[v["id"]] = v  # add or refresh
    return sorted(by_id.values(), key=sort_key, reverse=True)


def main():
    existing = load_existing()
    cid = resolve_channel_id(existing)
    if not cid:
        print("ERROR: no channel ID (set VD_CHANNEL_ID or data/videos.json channelId).",
              file=sys.stderr)
        return 1

    key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    fresh = None
    if key:
        try:
            fresh = fetch_all_via_api(cid, key)
            print(f"Data API: fetched {len(fresh)} videos (full catalog).")
        except Exception as e:  # noqa: BLE001
            print(f"WARNING: Data API failed ({e}); falling back to RSS.",
                  file=sys.stderr)
            fresh = None
    if fresh is None:
        try:
            fresh = parse_feed(fetch_feed(cid))
            print(f"RSS: fetched {len(fresh)} videos (latest 15; merging).")
        except Exception as e:  # noqa: BLE001
            print(f"WARNING: RSS fetch failed after retries: {e}. "
                  f"Keeping existing videos.json.", file=sys.stderr)
            return 0

    if not fresh:
        print("WARNING: source returned no videos; leaving existing data unchanged.",
              file=sys.stderr)
        return 0

    videos = merge(existing.get("videos", []), fresh)
    payload = {
        "updated": os.environ.get("VD_UPDATED", "").strip() or existing.get("updated"),
        "channelId": cid,
        "videos": videos,
    }
    DATA.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    print(f"Wrote {len(videos)} videos to {DATA.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
