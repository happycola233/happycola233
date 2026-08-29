#!/usr/bin/env python3
"""Generate a github-compact style activity graph SVG from recent contributions."""

from __future__ import annotations

import json
import math
import os
import ssl
import urllib.request
from datetime import date, datetime, timedelta, timezone
from html import escape
from pathlib import Path

# Do not read USERNAME: on Windows that is the local account name.
USERNAME = (
    os.environ.get("GRAPH_USERNAME")
    or os.environ.get("GITHUB_REPOSITORY_OWNER")
    or "happycola233"
)
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("TOKEN")
OUTPUT = Path(os.environ.get("OUTPUT_PATH") or "activity-graph/graph.svg")
DAYS = 31

# github-compact (Ashutosh00710/github-readme-activity-graph)
WIDTH = 1200
HEIGHT = 420
CHART_LEFT = 90
CHART_RIGHT = 1150
CHART_TOP = 80
CHART_BOTTOM = 350
COLOR = "8b949e"
LINE = "26a641"
POINT = "8b949e"
AREA = "26a641"

GRAPHQL_QUERY = """
query($login: String!) {
  user(login: $login) {
    name
    login
    contributionsCollection {
      contributionCalendar {
        weeks {
          contributionDays {
            date
            contributionCount
          }
        }
      }
    }
  }
}
"""


def http_json(url: str, *, data: dict | None = None, headers: dict[str, str] | None = None) -> dict:
    body = None if data is None else json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Accept": "application/json",
            "User-Agent": "happycola233-activity-graph",
            **(headers or {}),
        },
        method="POST" if body else "GET",
    )
    if body:
        req.add_header("Content-Type", "application/json")
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_profile() -> tuple[str, list[tuple[date, int]]]:
    if TOKEN:
        payload = http_json(
            "https://api.github.com/graphql",
            data={"query": GRAPHQL_QUERY, "variables": {"login": USERNAME}},
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        if payload.get("errors"):
            raise RuntimeError(payload["errors"])
        user = payload["data"]["user"]
        if not user:
            raise RuntimeError(f"GitHub user not found: {USERNAME}")
        days: list[tuple[date, int]] = []
        for week in user["contributionsCollection"]["contributionCalendar"]["weeks"]:
            for day in week["contributionDays"]:
                days.append(
                    (
                        date.fromisoformat(day["date"]),
                        int(day["contributionCount"]),
                    )
                )
        title_name = user.get("name") or user.get("login") or USERNAME
        return title_name, days

    profile = http_json(f"https://api.github.com/users/{USERNAME}")
    title_name = profile.get("name") or profile.get("login") or USERNAME
    contrib = http_json(f"https://github-contributions-api.jogruber.de/v4/{USERNAME}?y=last")
    days = [
        (date.fromisoformat(item["date"]), int(item["count"]))
        for item in contrib.get("contributions", [])
    ]
    return title_name, days


def last_n_days(days: list[tuple[date, int]], n: int) -> list[tuple[date, int]]:
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=n - 1)
    by_date = {d: c for d, c in days}
    return [(start + timedelta(days=i), by_date.get(start + timedelta(days=i), 0)) for i in range(n)]


def nice_ceiling(value: int) -> int:
    if value <= 0:
        return 10
    for nice in (10, 12, 16, 20, 24, 25, 30, 40, 50, 60, 80, 100):
        if nice >= value:
            return nice
    magnitude = 10 ** int(math.log10(value))
    for step in (1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        ceiling = int(step * magnitude)
        if ceiling >= value:
            return ceiling
    return int(math.ceil(value / 10) * 10)


def y_ticks(max_value: int) -> list[int]:
    top = nice_ceiling(max_value)
    for count in (10, 8, 5, 4):
        if top % count == 0:
            return list(range(0, top + 1, top // count))
    return list(range(0, top + 1, max(1, top // 10)))


def curve_path(points: list[tuple[float, float]]) -> str:
    """Monotone cubic (Fritsch–Carlson) so the line stays inside the plot."""
    n = len(points)
    if n == 0:
        return ""
    if n == 1:
        x, y = points[0]
        return f"M{x:.2f},{y:.2f}"

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    dx = [xs[i + 1] - xs[i] for i in range(n - 1)]
    slopes = [(ys[i + 1] - ys[i]) / dx[i] if dx[i] else 0.0 for i in range(n - 1)]

    tangents = [0.0] * n
    tangents[0] = slopes[0]
    tangents[-1] = slopes[-1]
    for i in range(1, n - 1):
        if slopes[i - 1] * slopes[i] <= 0:
            tangents[i] = 0.0
        else:
            tangents[i] = (slopes[i - 1] + slopes[i]) / 2

    for i in range(n - 1):
        if abs(slopes[i]) < 1e-12:
            tangents[i] = 0.0
            tangents[i + 1] = 0.0
            continue
        alpha = tangents[i] / slopes[i]
        beta = tangents[i + 1] / slopes[i]
        length = alpha * alpha + beta * beta
        if length > 9:
            tau = 3 / math.sqrt(length)
            tangents[i] = tau * alpha * slopes[i]
            tangents[i + 1] = tau * beta * slopes[i]

    parts = [f"M{xs[0]:.2f},{ys[0]:.2f}"]
    for i in range(n - 1):
        h = dx[i]
        c1x = xs[i] + h / 3
        c1y = ys[i] + tangents[i] * h / 3
        c2x = xs[i + 1] - h / 3
        c2y = ys[i + 1] - tangents[i + 1] * h / 3
        parts.append(f"C{c1x:.2f},{c1y:.2f},{c2x:.2f},{c2y:.2f},{xs[i + 1]:.2f},{ys[i + 1]:.2f}")
    return "".join(parts)


def scale_points(series: list[tuple[date, int]], y_max: int) -> list[tuple[float, float]]:
    count = max(len(series) - 1, 1)
    span = CHART_RIGHT - CHART_LEFT
    height = CHART_BOTTOM - CHART_TOP
    points = []
    for i, (_, value) in enumerate(series):
        x = CHART_LEFT + span * i / count
        y = CHART_BOTTOM - (value / y_max) * height
        points.append((x, y))
    return points


def render_svg(title_name: str, series: list[tuple[date, int]]) -> str:
    ticks = y_ticks(max((count for _, count in series), default=0))
    y_max = ticks[-1]
    points = scale_points(series, y_max)
    line_path = curve_path(points)
    area_path = (
        f"{line_path}L{points[-1][0]:.2f},{CHART_BOTTOM:.2f}"
        f"L{points[0][0]:.2f},{CHART_BOTTOM:.2f}Z"
        if points
        else ""
    )

    v_grid = []
    for x, _ in points:
        v_grid.append(
            f'<line x1="{x:.2f}" x2="{x:.2f}" y1="{CHART_TOP}" y2="{CHART_BOTTOM}" class="grid" />'
        )
    h_grid = []
    y_labels = []
    for tick in ticks:
        y = CHART_BOTTOM - (tick / y_max) * (CHART_BOTTOM - CHART_TOP)
        h_grid.append(
            f'<line x1="{CHART_LEFT}" x2="{CHART_RIGHT}" y1="{y:.2f}" y2="{y:.2f}" class="grid" />'
        )
        y_labels.append(
            f'<text x="{CHART_LEFT - 10}" y="{y + 4:.2f}" class="label" text-anchor="end">{tick}</text>'
        )

    x_labels = []
    for (x, _), (day, _) in zip(points, series):
        x_labels.append(
            f'<text x="{x:.2f}" y="370" class="label" text-anchor="middle">{day.day}</text>'
        )

    dots = [
        (
            f'<circle cx="{x:.2f}" cy="{y:.2f}" r="4.5" class="point">'
            f"<title>{day.isoformat()}: {value} contribution{'s' if value != 1 else ''}</title>"
            f"</circle>"
        )
        for (x, y), (day, value) in zip(points, series)
    ]

    title = escape(f"{title_name}'s Contribution Graph", quote=False)
    title_attr = escape(f"{title_name}'s Contribution Graph")
    return f"""<svg width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="{title_attr}">
  <title>{title}</title>
  <style>
    .title {{ font: 600 20px 'Segoe UI', Ubuntu, Sans-Serif; fill: #{COLOR}; }}
    .label {{ font: 600 12px 'Segoe UI', Ubuntu, Sans-Serif; fill: #{COLOR}; }}
    .grid {{ stroke: #{COLOR}; stroke-width: 1; stroke-opacity: 0.3; stroke-dasharray: 2; }}
    .line {{ fill: none; stroke: #{LINE}; stroke-width: 4; stroke-linecap: round; stroke-linejoin: round; }}
    .area {{ fill: #{AREA}; fill-opacity: 0.1; }}
    .point {{ fill: #{POINT}; }}
  </style>
  <rect width="100%" height="100%" fill="transparent" />
  <text x="{WIDTH / 2:.0f}" y="36" class="title" text-anchor="middle">{title}</text>
  <g class="grids">
    {''.join(v_grid)}
    {''.join(h_grid)}
  </g>
  <path d="{area_path}" class="area" />
  <path d="{line_path}" class="line" />
  <g class="points">{''.join(dots)}</g>
  <g class="x-labels">{''.join(x_labels)}</g>
  <g class="y-labels">{''.join(y_labels)}</g>
  <text x="{(CHART_LEFT + CHART_RIGHT) / 2:.0f}" y="400" class="label" text-anchor="middle">Days</text>
  <text x="20" y="{(CHART_TOP + CHART_BOTTOM) / 2:.0f}" class="label" text-anchor="middle" transform="rotate(-90, 20, {(CHART_TOP + CHART_BOTTOM) / 2:.0f})">Contributions</text>
</svg>
"""


def main() -> None:
    title_name, days = fetch_profile()
    series = last_n_days(days, DAYS)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(render_svg(title_name, series), encoding="utf-8")
    print(f"Wrote {OUTPUT} ({len(series)} days, user={title_name})")


if __name__ == "__main__":
    main()
