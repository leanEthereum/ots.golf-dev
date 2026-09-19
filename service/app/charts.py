"""Record history across scheme classes; an uncertified series stays off the numeric axis."""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from html import escape

W, H = 960, 410
ML, MR, MT = 48, 235, 30


def _nice_ticks(lo: float, hi: float) -> list[int]:
    # Keep the SVG small even at the maximum admissible claim (one million).
    target = max((hi - lo) / 8, 1)
    scale = 10 ** math.floor(math.log10(target))
    step = next(n * scale for n in (1, 2, 5, 10) if n * scale >= target)
    start = math.ceil(lo / step) * step
    return list(range(start, math.floor(hi) + 1, step))


def _time_ticks(t0: datetime, t1: datetime, n: int = 5) -> list[datetime]:
    span = (t1 - t0).total_seconds()
    return [t0 + timedelta(seconds=span * i / (n - 1)) for i in range(n)]


def record_chart(series: list[dict], now: datetime, *, unit: str = "compressions",
                 chart_id: str = "record-chart", title: str = "Verification bounds across three frameworks") -> dict:
    """Each series carries its own framework, kind, status and records. A series without records
    draws nothing; a pending one (no certificate interface) gets a lane outside the numeric axis."""
    numeric = [s for s in series if s.get("status") != "pending" and s["points"]]
    pending = [s for s in series if s.get("status") == "pending"]
    bottom_margin = 100 if pending else 45
    all_t = [p["t"] for s in numeric for p in s["points"]]
    t1 = max([now, *all_t])
    t0 = min(all_t) if all_t else now - timedelta(days=1)
    if t1 - t0 < timedelta(days=1):
        t0 = t1 - timedelta(days=1)
    t0 -= (t1 - t0) * 0.04
    tick_fmt = "%b %d %H:%M" if t1 - t0 < timedelta(days=3) else "%b %d"
    claims = [p["claim"] for s in numeric for p in s["points"]]
    y_lo, y_hi = max(min(claims, default=0) - 6, 0), max(claims, default=100) + 6
    y_lo, y_hi = int(y_lo // 5) * 5, int(-(-y_hi // 5)) * 5

    def sx(t: datetime) -> float:
        return ML + (W - ML - MR) * (t - t0).total_seconds() / max((t1 - t0).total_seconds(), 1)

    def sy(v: float) -> float:
        return MT + (H - MT - bottom_margin) * (y_hi - v) / max(y_hi - y_lo, 1)

    chart_id = escape(chart_id)
    description = ("Verification costs on every execution. Smaller is better. " if unit == "cycles" else
                   "Lower bounds rise and upper bounds fall. Each lower framework has its own series. ")
    out = [f'<svg viewBox="0 0 {W} {H}" class="record-chart" role="group" data-unit="{escape(unit)}" '
           f'aria-labelledby="{chart_id}-title {chart_id}-desc">',
           f'<title id="{chart_id}-title">{escape(title)}</title>',
           f'<desc id="{chart_id}-desc">{description}'
           'Hover or focus a record for its track and solver.</desc>']
    for v in _nice_ticks(y_lo, y_hi):
        y = sy(v)
        out.append(f'<line class="grid" x1="{ML}" x2="{W - MR}" y1="{y:.1f}" y2="{y:.1f}"/>')
        label = f"{v // 1000}k" if v >= 10000 and v % 1000 == 0 else str(v)
        out.append(f'<text class="tick" x="{ML - 8}" y="{y + 4:.1f}" text-anchor="end">{label}</text>')
    out.append(f'<line class="axis" x1="{ML}" x2="{W - MR}" y1="{H - bottom_margin}" y2="{H - bottom_margin}"/>')
    for t in _time_ticks(t0, t1):
        out.append(f'<text class="tick" x="{sx(t):.1f}" y="{H - bottom_margin + 20}" text-anchor="middle">{t.strftime(tick_fmt)}</text>')
    out.append(f'<text class="tick" x="4" y="{MT - 14}">{escape(unit)}</text>')

    # Keep endpoint labels distinct even when different series have equal costs.
    ends = sorted((sy(s["points"][-1]["claim"]), s["slug"]) for s in numeric)
    label_y = {}
    prev = MT - 28
    for y, slug in ends:
        label_y[slug] = max(y, prev + 28)
        prev = label_y[slug]
    overflow = max(prev - (H - bottom_margin - 4), 0)
    label_y = {slug: y - overflow for slug, y in label_y.items()}

    points = []
    for s in numeric:
        slug, label = escape(s["slug"]), escape(s["label"])
        cls = f'f-{s["framework"]} {s["kind"]}'
        pts = s["points"]
        status = s.get("status", "certified")
        out.append(f'<g class="chart-series {cls}" data-series="{slug}" data-kind="{s["kind"]}" data-status="{status}">')
        last_claim = pts[-1]["claim"]
        # Record history begins with its first submission, with no invented earlier step.
        d = f'M{sx(pts[0]["t"]):.1f},{sy(pts[0]["claim"]):.1f}'
        for p in pts[1:]:
            d += f' H{sx(p["t"]):.1f} V{sy(p["claim"]):.1f}'
        d += f' H{sx(t1):.1f}'
        out.append(f'<path class="line" d="{d}"/>')
        for p in pts:
            x, y = sx(p["t"]), sy(p["claim"])
            point = {"x": round(x, 1), "y": round(y, 1), "track": s["label"], "framework": s["framework"],
                     "kind": s["kind"], "claim": p["claim"], "login": p["login"],
                     "date": p["t"].strftime("%Y-%m-%d %H:%M UTC"), "id": p["id"], "demo": p.get("demo", False),
                     "unit": unit[:-1] if p["claim"] == 1 else unit}
            demo_label = " · demo" if point["demo"] else ""
            point_title = escape(f'{s["label"]}: {p["claim"]} {point["unit"]} · {p["login"]} · {point["date"]}{demo_label}')
            out.append(f'<a href="/submissions/{escape(p["id"])}" class="chart-record" data-point="{len(points)}" aria-label="{point_title}">'
                       f'<circle class="hit-area" cx="{x:.1f}" cy="{y:.1f}" r="16"/>'
                       f'<circle class="mark" cx="{x:.1f}" cy="{y:.1f}" r="4.5"><title>{point_title}</title></circle></a>')
            points.append(point)
        end_y, text_y = sy(last_claim), label_y[s["slug"]]
        out.append(f'<path class="connector" d="M{sx(t1):.1f},{end_y:.1f} L{sx(t1) + 12:.1f},{text_y:.1f} H{sx(t1) + 18:.1f}"/>')
        demo_label = " · demo" if pts[-1].get("demo") else ""
        out.append(f'<text class="label" x="{sx(t1) + 23:.1f}" y="{text_y + 4:.1f}">'
                   f'<tspan class="label-name">{label}</tspan><tspan class="label-dot"> · </tspan>'
                   f'<tspan class="label-value">{last_claim}</tspan><tspan class="label-demo">{demo_label}</tspan></text>')
        out.append('</g>')

    # This lane has no y-axis value. Pending never becomes a fabricated zero or a record point.
    for i, s in enumerate(pending):
        y = H - 30 + i * 24
        out.append(f'<g class="chart-series f-{s["framework"]} {s["kind"]} pending" data-series="{escape(s["slug"])}" '
                   f'data-kind="{s["kind"]}" data-status="pending">'
                   f'<path class="line" d="M{ML},{y} H{W - MR}"/>'
                   f'<text class="label" x="{W - MR + 23}" y="{y + 4}">{escape(s["label"])}: pending</text>'
                   f'<text class="tick" x="{ML}" y="{y - 10}">No certified bound · outside the numeric axis</text></g>')
    if not numeric:
        out.append(f'<text class="tick empty-chart" x="{(ML + W - MR) / 2:.1f}" y="{(MT + H - bottom_margin) / 2:.1f}" '
                   'text-anchor="middle">No records yet</text>')
    out.append(f'<line class="crosshair" x1="0" x2="0" y1="{MT}" y2="{H - bottom_margin}" visibility="hidden"/>')
    out.append('</svg>')
    return {"svg": '\n'.join(out), "points": json.dumps(points).replace('<', '\\u003c'), "series": series}
