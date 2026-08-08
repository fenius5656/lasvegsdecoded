#!/usr/bin/env python3
"""
Vegas Decoded — YouTube video sync
----------------------------------
Fetches the channel's public RSS feed and writes data/videos.json.
No API key required. Runs on GitHub Actions (see .github/workflows/sync-videos.yml).

Channel ID resolution order:
  1. env var  VD_CHANNEL_ID
  2. "channelId" field already saved in data/videos.json

A YouTube channel ID looks like: UCxxxxxxxxxxxxxxxxxxxxxx (starts with "UC").
Find yours at https://www.youtube.com/account_advanced while logged in,
or use the resolver instructions in README.md.
"""

import json
import os
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "videos.json"

FEED = "https://www.youtube.com/feeds/videos.xml?channel_id={cid}"
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
    "media": "http://search.yahoo.com/mrss/",
}


def load_existing():
    if DATA.exists():
        try:
            return json.loads(DATA.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"updated": None, "channelId": "", "videos": []}


def resolve_channel_id(existing):
    cid = os.environ.get("VD_CHANNEL_ID", "").strip()
    if not cid:
        cid = (existing.get("channelId") or "").strip()
    return cid


def fetch_feed(cid):
    url = FEED.format(cid=cid)
    req = urllib.request.Request(url, headers={"User-Agent": "VegasDecodedSync/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def parse_feed(xml_bytes):
    root = ET.fromstring(xml_bytes)
    videos = []
    for entry in root.findall("atom:entry", NS):
        vid = entry.findtext("yt:videoId", default="", namespaces=NS)
        title = entry.findtext("atom:title", default="", namespaces=NS)
        published = entry.findtext("atom:published", default="", namespaces=NS)
        thumb_el = entry.find(".//media:thumbnail", NS)
        thumb = thumb_el.get("url") if thumb_el is not None else ""
        if not thumb and vid:
            thumb = f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
        if vid:
            videos.append({
                "id": vid,
                "title": title.strip(),
                "published": published,
                "thumbnail": thumb,
            })
    return videos


def main():
    existing = load_existing()
    cid = resolve_channel_id(existing)
    if not cid:
        print("ERROR: No channel ID set. Set VD_CHANNEL_ID or add "
              "\"channelId\" to data/videos.json.", file=sys.stderr)
        return 1

    try:
        xml_bytes = fetch_feed(cid)
        videos = parse_feed(xml_bytes)
    except Exception as e:  # noqa: BLE001
        print(f"ERROR fetching/parsing feed: {e}", file=sys.stderr)
        return 1

    if not videos:
        print("WARNING: feed returned no videos; leaving existing data unchanged.",
              file=sys.stderr)
        return 0

    payload = {
        "updated": None,  # stamped by CI below via UPDATED env if provided
        "channelId": cid,
        "videos": videos,
    }
    updated = os.environ.get("VD_UPDATED", "").strip()
    payload["updated"] = updated or existing.get("updated")

    DATA.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    print(f"Wrote {len(videos)} videos to {DATA.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
