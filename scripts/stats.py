"""Render the profile stats cards (overview + languages) as SVG.

Usage: GH_TOKEN=<token> python3 scripts/stats.py <out_dir>

The token needs the `repo` and `read:user` scopes so private repositories
and private contributions are counted.
"""

import json
import os
import sys
import urllib.request
from datetime import date
from xml.sax.saxutils import escape

API = "https://api.github.com/graphql"

THEMES = {
    "dark": {"bg": "#0d1117", "border": "#30363d", "text": "#e6edf3",
             "muted": "#7d8590", "label": "#8b949e", "other": "#6e7681"},
    "light": {"bg": "#ffffff", "border": "#d0d7de", "text": "#1f2328",
              "muted": "#656d76", "label": "#57606a", "other": "#8c959f"},
}

# Languages shown under one legend entry.
MERGE = {"CSS": "HTML", "SCSS": "HTML"}
LABELS = {"HTML": "HTML / CSS"}
TOP_N = 5

FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"


def graphql(token, query, variables=None):
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(API, data=body, headers={
        "Authorization": f"bearer {token}",
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.load(resp)
    if payload.get("errors"):
        raise RuntimeError(payload["errors"])
    return payload["data"]


def fetch(token):
    base = graphql(token, """
      query {
        viewer {
          contributionsCollection {
            contributionYears
            contributionCalendar {
              totalContributions
              weeks { contributionDays { date contributionCount } }
            }
          }
        }
      }""")["viewer"]["contributionsCollection"]

    years = base["contributionYears"]
    year_fields = "\n".join(
        f'y{y}: contributionsCollection(from: "{y}-01-01T00:00:00Z", to: "{y}-12-31T23:59:59Z") '
        "{ contributionCalendar { totalContributions } }"
        for y in years
    )
    per_year = graphql(token, f"query {{ viewer {{ {year_fields} }} }}")["viewer"]

    repos, cursor = [], None
    while True:
        page = graphql(token, """
          query($cursor: String) {
            viewer {
              repositories(ownerAffiliations: OWNER, isFork: false, first: 100, after: $cursor) {
                pageInfo { hasNextPage endCursor }
                nodes {
                  isArchived
                  languages(first: 50) { edges { size node { name color } } }
                }
              }
            }
          }""", {"cursor": cursor})["viewer"]["repositories"]
        repos += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]

    calendar = base["contributionCalendar"]
    days = [(d["date"], d["contributionCount"])
            for w in calendar["weeks"] for d in w["contributionDays"]]
    return {
        "total": sum(v["contributionCalendar"]["totalContributions"] for v in per_year.values()),
        "past_year": calendar["totalContributions"],
        "days": days,
        "repos": repos,
    }


def current_streak(days):
    """Consecutive days with contributions, ending today or yesterday.

    `days` is a list of (iso_date, count) in chronological order; the last
    entry is today. An empty today does not break the streak, since the day
    is not over yet.
    """
    counts = [c for _, c in days]
    if counts and counts[-1] == 0:
        counts = counts[:-1]
    streak = 0
    for c in reversed(counts):
        if c == 0:
            break
        streak += 1
    return streak


def language_shares(repos):
    """Top languages by bytes across active (non-archived) repos.

    Returns (shares, repo_count) where shares is a list of
    (label, color, percent) with the tail folded into "Other".
    """
    sizes, colors, counted = {}, {}, 0
    for repo in repos:
        if repo["isArchived"]:
            continue
        edges = repo["languages"]["edges"]
        if edges:
            counted += 1
        for e in edges:
            name = MERGE.get(e["node"]["name"], e["node"]["name"])
            sizes[name] = sizes.get(name, 0) + e["size"]
            if name == e["node"]["name"]:
                colors[name] = e["node"]["color"]

    total = sum(sizes.values())
    if not total:
        return [], counted
    ranked = sorted(sizes.items(), key=lambda kv: kv[1], reverse=True)
    shares = [(LABELS.get(n, n), colors.get(n) or "#8b949e", s / total * 100)
              for n, s in ranked[:TOP_N]]
    rest = sum(s for _, s in ranked[TOP_N:])
    if rest:
        shares.append(("Other", None, rest / total * 100))
    return shares, counted


def card(theme, title, subtitle, body):
    t = THEMES[theme]
    return f"""<svg width="410" height="170" viewBox="0 0 410 170" fill="none" xmlns="http://www.w3.org/2000/svg">
  <style>
    .title {{ font: 600 14px {FONT}; fill: {t["text"]}; }}
    .sub {{ font: 400 11px {FONT}; fill: {t["muted"]}; }}
    .label {{ font: 400 12px {FONT}; fill: {t["label"]}; }}
    .val {{ font: 600 13px {FONT}; fill: {t["text"]}; }}
    .lang {{ font: 600 12px {FONT}; fill: {t["text"]}; }}
    .pct {{ font: 400 12px {FONT}; fill: {t["muted"]}; }}
  </style>
  <rect x="0.5" y="0.5" width="409" height="169" rx="6" fill="{t["bg"]}" stroke="{t["border"]}"/>
  <text x="20" y="30" class="title">{escape(title)}</text>
  <text x="390" y="30" text-anchor="end" class="sub">{escape(subtitle)}</text>
{body}
</svg>
"""


def render_overview(stats, theme):
    rows = [
        ("Total Contributions", f"{stats['total']:,}"),
        ("Past Year", f"{stats['past_year']:,}"),
        ("Repositories", f"{len(stats['repos']):,}"),
        ("Current Streak", f"{stats['streak']} day{'' if stats['streak'] == 1 else 's'}"),
    ]
    body = "\n".join(
        f'  <text x="20" y="{64 + i * 28}" class="label">{escape(label)}</text>\n'
        f'  <text x="390" y="{64 + i * 28}" text-anchor="end" class="val">{escape(value)}</text>'
        for i, (label, value) in enumerate(rows)
    )
    return card(theme, "Activity", "includes private", body)


def render_langs(shares, repo_count, theme):
    other = THEMES[theme]["other"]
    bar_x, bar_w, gap = 20, 370, 1
    usable = bar_w - gap * (len(shares) - 1)
    segments, x = [], bar_x
    for i, (_, color, pct) in enumerate(shares):
        # The last segment absorbs rounding so the bar always ends flush.
        w = bar_x + bar_w - x if i == len(shares) - 1 else round(usable * pct / 100)
        segments.append(f'    <rect x="{x}" y="46" width="{max(w, 1)}" height="8" fill="{color or other}"/>')
        x += w + gap

    legend = []
    for i, (label, color, pct) in enumerate(shares):
        col, row = divmod(i, 3)
        cx, cy = 25 + col * 190, 80 + row * 28
        legend.append(
            f'  <circle cx="{cx}" cy="{cy}" r="4.5" fill="{color or other}"/>\n'
            f'  <text x="{cx + 11}" y="{cy + 4}"><tspan class="lang">{escape(label)}</tspan> '
            f'<tspan class="pct">{pct:.1f}%</tspan></text>'
        )

    body = f"""  <clipPath id="bar-clip">
    <rect x="{bar_x}" y="46" width="{bar_w}" height="8" rx="4"/>
  </clipPath>
  <g clip-path="url(#bar-clip)">
{chr(10).join(segments)}
  </g>
{chr(10).join(legend)}"""
    return card(theme, "Languages", f"across {repo_count} repos", body)


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "out"
    token = os.environ.get("GH_TOKEN")
    if not token:
        sys.exit("GH_TOKEN is not set")

    stats = fetch(token)
    stats["streak"] = current_streak(stats["days"])
    shares, repo_count = language_shares(stats["repos"])

    os.makedirs(out_dir, exist_ok=True)
    for theme in THEMES:
        with open(os.path.join(out_dir, f"overview-{theme}.svg"), "w") as f:
            f.write(render_overview(stats, theme))
        with open(os.path.join(out_dir, f"langs-{theme}.svg"), "w") as f:
            f.write(render_langs(shares, repo_count, theme))

    print(f"{date.today()}: total={stats['total']} past_year={stats['past_year']} "
          f"repos={len(stats['repos'])} streak={stats['streak']} "
          f"langs={[(l, round(p, 1)) for l, _, p in shares]}")


if __name__ == "__main__":
    main()
