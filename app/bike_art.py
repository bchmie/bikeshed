"""The bike-drawing zone manifest (copied from the accepted dashboard prototype).

The art itself is one traced path; per-part highlighting is geometric, so this
module is the only art-specific data the app carries.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.models import Part

_ART_PATH = Path(__file__).parent / "bike_art.json"
ART: dict = json.loads(_ART_PATH.read_text())
REGIONS: dict[str, dict] = ART["regions"]
# The traced path lives in a translated coordinate space; the <img> draws it in
# the drawing's own space, so the overlay viewBox must start at the origin.
_vb = ART["viewBox"].split()
DRAWING_VIEWBOX = f"0 0 {_vb[2]} {_vb[3]}"

ZONE_BY_TYPE = {
    "chain": "chain",
    "quicklink": "quicklink",
    "cassette": "cassette",
    "chainring": "chainring",
    "bottom_bracket": "chainring",
}

LOCATION_ZONES = {
    "tire": ("front-tire", "rear-tire"),
    "tubeless_wheelset": ("front-tire", "rear-tire"),
    "brake_pads": ("pads-front", "pads-rear"),
    "sealant": ("front-tire", "rear-tire"),
}


def zone_for(part: Part) -> str | None:
    if part.part_type_key in ZONE_BY_TYPE:
        return ZONE_BY_TYPE[part.part_type_key]
    zones = LOCATION_ZONES.get(part.part_type_key)
    if zones is None:
        return None
    return zones[0] if part.location == "front" else zones[1]


def shapes_for(zone: str) -> list[dict]:
    region = REGIONS.get(zone)
    return region["shapes"] if region else []


def pin_for(zone: str) -> tuple[float, float]:
    region = REGIONS.get(zone)
    if region:
        return tuple(region["pin"])
    return (842, 509)
