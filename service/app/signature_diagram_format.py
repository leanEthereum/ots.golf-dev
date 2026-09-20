"""Bounded, data-only owner diagram registry and static SVG validation."""
from __future__ import annotations

import json
import math
import re
import xml.etree.ElementTree as ET

REGISTRY_PATH = "signature-diagrams.json"
MAX_REGISTRY_BYTES = 256 * 1024
MAX_IMAGE_BYTES = 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024
MAX_DIAGRAMS = 64
SVG_NS = "http://www.w3.org/2000/svg"
TAGS = frozenset("svg g defs title desc style path rect circle ellipse line polyline polygon text tspan "
                 "textPath linearGradient radialGradient stop clipPath mask pattern marker symbol use".split())
SVG_TAGS = frozenset(f"{{{SVG_NS}}}{tag}" for tag in TAGS)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def parse_registry(raw: bytes) -> tuple[dict, dict]:
    if len(raw) > MAX_REGISTRY_BYTES:
        raise ValueError("diagram registry exceeds 256 KiB")
    try:
        data = json.loads(raw, object_pairs_hook=_unique)
    except (UnicodeError, RecursionError) as exc:
        raise ValueError("invalid diagram registry JSON") from exc
    if (not isinstance(data, dict) or set(data) != {"version", "diagrams"}
            or type(data["version"]) is not int or data["version"] != 1
            or not isinstance(data["diagrams"], dict) or len(data["diagrams"]) > MAX_DIAGRAMS):
        raise ValueError("expected version 1 and at most 64 diagrams")
    diagrams, errors = {}, {}
    for sid, item in data["diagrams"].items():
        if (not re.fullmatch(r"[0-9a-f]{1,32}", sid)
                or not isinstance(item, dict)
                or not {"commit", "contract", "image", "alt"} <= set(item)
                or not set(item) <= {"commit", "contract", "image", "alt", "intuition"}
                or not isinstance(item["commit"], str) or not re.fullmatch(r"[0-9a-f]{40}", item["commit"])
                or not isinstance(item["contract"], str) or not re.fullmatch(r"[0-9a-f]{64}", item["contract"])
                or not isinstance(item["image"], str)
                or not re.fullmatch(r"signature-diagrams/[A-Za-z0-9][A-Za-z0-9_-]{0,100}\.svg", item["image"])
                or not isinstance(item["alt"], str) or not 1 <= len(item["alt"].strip()) <= 4096
                or ("intuition" in item and (not isinstance(item["intuition"], str)
                    or not 1 <= len(item["intuition"].strip()) <= 1024))):
            errors[sid] = "expected checked commit, contract, signature-diagrams/<name>.svg and alt text"
        else:
            diagrams[sid] = dict(item)
    return diagrams, errors


def _safe_css(value: str) -> None:
    # No imports, escapes, or external resources. CSP independently blocks network access.
    if "@" in value or "\\" in value or "/*" in value:
        raise ValueError("SVG CSS must be self-contained, without imports or escapes")
    for target in re.findall(r"url\s*\((.*?)\)", value, flags=re.I | re.S):
        if not re.fullmatch(r"#[A-Za-z_][A-Za-z0-9_.:-]*", target.strip().strip("\"'")):
            raise ValueError("SVG resource references must name an internal #id")


def validate_svg(raw: bytes) -> tuple[float, float]:
    """Accept static, self-contained UTF-8 SVG; return its intrinsic viewBox size.

    Images are served under a sandbox CSP and used only via <img>, never inline.
    This is a deliberately small static SVG subset, not an HTML sanitizer.
    """
    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError("SVG exceeds 1 MiB")
    try:
        text = raw.decode("utf-8-sig")
        if re.search(r"<!DOCTYPE|<!ENTITY|<\?xml-stylesheet", text, re.I):
            raise ValueError("SVG DTDs, entities and external stylesheets are forbidden")
        root = ET.fromstring(text)
    except (UnicodeError, ET.ParseError, RecursionError) as exc:
        raise ValueError("invalid UTF-8 SVG") from exc
    if root.tag != f"{{{SVG_NS}}}svg":
        raise ValueError("expected an SVG document")
    try:
        box = [float(x) for x in re.split(r"[\s,]+", root.attrib["viewBox"].strip())]
        if (len(box) != 4 or not all(math.isfinite(x) for x in box)
                or not all(0 < x <= 10000 for x in box[2:])):
            raise ValueError
    except (KeyError, ValueError):
        raise ValueError("SVG needs a finite viewBox with positive dimensions up to 10000") from None
    for count, node in enumerate(root.iter(), 1):
        if count > 20000 or node.tag not in SVG_TAGS:
            raise ValueError("SVG contains unsupported elements or more than 20000 nodes")
        if node.tag == f"{{{SVG_NS}}}style":
            _safe_css(node.text or "")
        for key, value in node.attrib.items():
            if key.startswith("{") and key not in {
                    "{http://www.w3.org/XML/1998/namespace}space",
                    "{http://www.w3.org/1999/xlink}href"}:
                raise ValueError("unsupported SVG attribute namespace")
            name = key.rsplit("}", 1)[-1].lower()
            if name.startswith("on") or name in {"src", "base"}:
                raise ValueError("SVG event handlers and external sources are forbidden")
            if name == "href" and not re.fullmatch(r"#[A-Za-z_][A-Za-z0-9_.:-]*", value):
                raise ValueError("SVG links may only reference an internal #id")
            if name == "style" or "url" in value.lower():
                _safe_css(value)
    return box[2], box[3]
