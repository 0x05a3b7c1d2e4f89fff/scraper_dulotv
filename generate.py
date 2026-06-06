#!/usr/bin/env python3
"""
dulo-tv-epg — generate.py
Fetches live channel data from dulo.tv, produces:
  - dulo.m3u       (M3U playlist with EPG header)
  - dulo.xml.gz    (merged XMLTV EPG, gzip-compressed)

EPG data sourced from epg.pw per-channel XML API.
Run every 4 hours via GitHub Actions to handle tokenised stream URLs.
"""

import gzip
import json
import re
import sys
import time
from xml.etree import ElementTree as ET

import requests

# ── Config ────────────────────────────────────────────────────────────────────
REPO        = "BuddyChewChew/dulo-tv-epg"   # ← your GitHub repo name
BRANCH      = "main"
BASE_RAW    = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}"
EPG_URL     = f"{BASE_RAW}/dulo.xml.gz"
M3U_OUT     = "dulo.m3u"
EPG_OUT     = "dulo.xml.gz"

CHANNELS_API = "https://dulo.tv/api/live-tv/channels"
EPG_API      = "https://epg.pw/api/epg.xml?channel_id={channel_id}"

# Delay between epg.pw calls to be polite
EPG_FETCH_DELAY = 0.5   # seconds

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; dulo-tv-epg/1.0)"
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def extract_epg_channel_id(epg_source_url: str) -> str | None:
    """Pull numeric channel_id out of an epg.pw URL.

    Handles both:
      https://epg.pw/last/467679.html?lang=en   → 467679
      https://epg.pw/api/epg.xml?channel_id=467679 → 467679
    """
    if not epg_source_url:
        return None
    m = re.search(r"channel_id=(\d+)", epg_source_url)
    if m:
        return m.group(1)
    m = re.search(r"/(\d+)\.html", epg_source_url)
    if m:
        return m.group(1)
    return None


def fetch_channels() -> list[dict]:
    print("Fetching channel list from dulo.tv …")
    r = requests.get(CHANNELS_API, headers=HEADERS, timeout=30)
    r.raise_for_status()
    data = r.json()
    channels = data.get("channels", data) if isinstance(data, dict) else data
    print(f"  → {len(channels)} channels")
    return channels


def build_m3u(channels: list[dict]) -> str:
    lines = [f'#EXTM3U url-tvg="{EPG_URL}" x-tvg-url="{EPG_URL}"\n']
    for ch in channels:
        ch_id   = ch.get("id", "")
        name    = ch.get("name", "Unknown")
        logo    = ch.get("logo_url", "")
        group   = ch.get("category", "General").title()
        stream  = ch.get("source_url", "")

        # Use channel uuid as tvg-id so it matches XMLTV <channel id="…">
        epg_cid = extract_epg_channel_id(ch.get("epg_source_url", "")) or ch_id

        if not stream:
            continue

        lines.append(
            f'#EXTINF:-1 tvg-id="{epg_cid}" tvg-name="{name}" '
            f'tvg-logo="{logo}" group-title="{group}",{name}\n'
            f'{stream}\n'
        )
    return "".join(lines)


def fetch_epg_xml(channel_id: str) -> ET.Element | None:
    """Fetch XMLTV XML for one channel from epg.pw; return root Element or None."""
    url = EPG_API.format(channel_id=channel_id)
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        if r.status_code != 200:
            return None
        root = ET.fromstring(r.content)
        return root
    except Exception as e:
        print(f"    [warn] EPG fetch failed for channel_id={channel_id}: {e}")
        return None


def build_epg(channels: list[dict]) -> bytes:
    """Fetch per-channel EPG XML from epg.pw and merge into one XMLTV document."""
    tv = ET.Element("tv", attrib={
        "source-info-name": "epg.pw",
        "generator-info-name": f"github.com/{REPO}",
    })

    seen_channels: set[str] = set()
    programme_elements: list[ET.Element] = []

    total = len(channels)
    for i, ch in enumerate(channels, 1):
        epg_source = ch.get("epg_source_url", "")
        ch_id = extract_epg_channel_id(epg_source)
        if not ch_id:
            continue

        print(f"  [{i}/{total}] EPG for {ch.get('name', ch_id)} (id={ch_id})")
        root = fetch_epg_xml(ch_id)
        if root is None:
            time.sleep(EPG_FETCH_DELAY)
            continue

        # Collect <channel> elements (deduplicate)
        for chan_el in root.findall("channel"):
            cid = chan_el.get("id", "")
            if cid and cid not in seen_channels:
                seen_channels.add(cid)
                tv.append(chan_el)

        # Collect all <programme> elements
        for prog_el in root.findall("programme"):
            programme_elements.append(prog_el)

        time.sleep(EPG_FETCH_DELAY)

    # Append programmes after all channels
    for prog_el in programme_elements:
        tv.append(prog_el)

    xml_bytes = b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(tv, encoding="unicode").encode()
    return xml_bytes


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    channels = fetch_channels()

    # ── M3U ──
    print("\nBuilding M3U playlist …")
    m3u_content = build_m3u(channels)
    with open(M3U_OUT, "w", encoding="utf-8") as f:
        f.write(m3u_content)
    print(f"  → wrote {M3U_OUT} ({len(m3u_content):,} bytes)")

    # ── EPG ──
    print("\nFetching EPG data from epg.pw …")
    xml_bytes = build_epg(channels)
    with gzip.open(EPG_OUT, "wb") as f:
        f.write(xml_bytes)
    print(f"  → wrote {EPG_OUT} ({len(xml_bytes):,} bytes uncompressed)")

    print("\nDone.")


if __name__ == "__main__":
    main()
