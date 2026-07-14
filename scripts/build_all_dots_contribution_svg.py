from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import dataclass
from datetime import date
from html import escape
from pathlib import Path


QUERY = r"""
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays {
            date
            weekday
            contributionCount
            contributionLevel
          }
        }
      }
    }
  }
}
"""

LEVEL_INDEX = {
    "NONE": 0,
    "FIRST_QUARTILE": 1,
    "SECOND_QUARTILE": 2,
    "THIRD_QUARTILE": 3,
    "FOURTH_QUARTILE": 4,
}

GITHUB_DARK_COLORS = {
    0: "#161b22",
    1: "#0e4429",
    2: "#006d32",
    3: "#26a641",
    4: "#39d353",
}

AMMO_COLOR = "#39d353"
AMMO_RADIUS = 5.5
GRID_X = 237
GRID_Y = 107
CELL_SIZE = 11
CELL_GAP = 4
CELL_STEP = CELL_SIZE + CELL_GAP
PLANT_X = 198
PLANT_Y = 151
ZOMBIE_X = 1095
ZOMBIE_Y = 151
# Deliberately paced like Platane/snk: each consumption remains readable,
# while successive dots still overlap enough to feel like one continuous run.
START_DELAY = 0.70
SHOT_INTERVAL = 0.26
LOAD_TIME = 0.52
FLIGHT_TIME = 0.80
END_PAUSE = 1.50
MIN_DURATION = 7.0


@dataclass(frozen=True)
class Day:
    date: str
    weekday: int
    count: int
    level: int
    week_index: int

    @property
    def x(self) -> float:
        return GRID_X + self.week_index * CELL_STEP

    @property
    def y(self) -> float:
        return GRID_Y + self.weekday * CELL_STEP

    @property
    def cx(self) -> float:
        return self.x + CELL_SIZE / 2

    @property
    def cy(self) -> float:
        return self.y + CELL_SIZE / 2

    @property
    def snake_order(self) -> tuple[int, int]:
        row = self.weekday if self.week_index % 2 == 0 else 6 - self.weekday
        return self.week_index, row


@dataclass(frozen=True)
class Timing:
    take: float
    loaded: float
    impact: float


def gh_json(*args: str) -> dict:
    result = subprocess.run(
        ["gh", *args],
        check=True,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )
    return json.loads(result.stdout)


def fmt(value: float) -> str:
    return f"{value:.5f}".rstrip("0").rstrip(".")


def timeline(active_count: int) -> tuple[list[Timing], float]:
    timings: list[Timing] = []
    for index in range(active_count):
        take = START_DELAY + index * SHOT_INTERVAL
        loaded = take + LOAD_TIME
        impact = loaded + FLIGHT_TIME
        timings.append(Timing(take=take, loaded=loaded, impact=impact))
    final_impact = timings[-1].impact if timings else START_DELAY
    duration = max(MIN_DURATION, final_impact + END_PAUSE)
    return timings, duration


def month_labels(days: list[Day]) -> list[str]:
    first_day_by_week: dict[int, Day] = {}
    for day in days:
        current = first_day_by_week.get(day.week_index)
        if current is None or day.date < current.date:
            first_day_by_week[day.week_index] = day

    labels: list[str] = []
    previous_month: int | None = None
    for week_index in sorted(first_day_by_week):
        week_date = date.fromisoformat(first_day_by_week[week_index].date)
        if week_date.month == previous_month:
            continue
        previous_month = week_date.month
        x = GRID_X + week_index * CELL_STEP
        labels.append(
            f'    <text x="{fmt(x)}" y="101" fill="#8b949e" '
            f'font-family="-apple-system, BlinkMacSystemFont, Segoe UI, sans-serif" font-size="10">{week_date.strftime("%b")}</text>'
        )
    return labels


def calendar_markup(
    days: list[Day],
    ordered_active: list[Day],
    timings: list[Timing],
    duration: float,
    login: str,
    total: int,
) -> str:
    timing_by_date = {day.date: timing for day, timing in zip(ordered_active, timings)}
    cells: list[str] = []

    for day in days:
        title = escape(f"{day.date}: {day.count} contributions")
        fill = GITHUB_DARK_COLORS[day.level]
        if day.count == 0:
            cells.append(
                f'    <rect x="{fmt(day.x)}" y="{fmt(day.y)}" width="{CELL_SIZE}" height="{CELL_SIZE}" '
                f'rx="2" fill="{fill}"><title>{title}</title></rect>'
            )
            continue

        timing = timing_by_date[day.date]
        take_key = timing.take / duration
        cells.extend(
            [
                f'    <rect x="{fmt(day.x)}" y="{fmt(day.y)}" width="{CELL_SIZE}" height="{CELL_SIZE}" rx="2" fill="{fill}">',
                f'      <title>{title}</title>',
                '      <animate attributeName="opacity" values="1;0;0" '
                f'keyTimes="0;{fmt(take_key)};1" calcMode="discrete" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
                "    </rect>",
            ]
        )

    return "\n".join(
        [
            "  <!-- GitHub Contribution Calendar UI: 11px cells with 4px border spacing. -->",
            f'  <text x="190" y="77" fill="#c9d1d9" font-family="-apple-system, BlinkMacSystemFont, Segoe UI, sans-serif" font-size="13">{total} contributions in the last year</text>',
            '  <rect x="190" y="84" width="891" height="143" rx="6" fill="#0d1117" fill-opacity=".9" stroke="#30363d"/>',
            '  <g id="github-month-labels">',
            *month_labels(days),
            "  </g>",
            '  <g id="github-weekday-labels" fill="#8b949e" font-family="-apple-system, BlinkMacSystemFont, Segoe UI, sans-serif" font-size="10" text-anchor="end">',
            f'    <text x="229" y="{fmt(GRID_Y + CELL_STEP + 8.5)}">Mon</text>',
            f'    <text x="229" y="{fmt(GRID_Y + CELL_STEP * 3 + 8.5)}">Wed</text>',
            f'    <text x="229" y="{fmt(GRID_Y + CELL_STEP * 5 + 8.5)}">Fri</text>',
            "  </g>",
            '  <g id="github-contribution-cells">',
            *cells,
            "  </g>",
            '  <g id="github-contribution-legend" font-family="-apple-system, BlinkMacSystemFont, Segoe UI, sans-serif" font-size="10" fill="#8b949e">',
            '    <text x="918" y="220">Less</text>',
            f'    <rect x="946" y="211" width="10" height="10" rx="2" fill="{GITHUB_DARK_COLORS[0]}"/>',
            f'    <rect x="960" y="211" width="10" height="10" rx="2" fill="{GITHUB_DARK_COLORS[1]}"/>',
            f'    <rect x="974" y="211" width="10" height="10" rx="2" fill="{GITHUB_DARK_COLORS[2]}"/>',
            f'    <rect x="988" y="211" width="10" height="10" rx="2" fill="{GITHUB_DARK_COLORS[3]}"/>',
            f'    <rect x="1002" y="211" width="10" height="10" rx="2" fill="{GITHUB_DARK_COLORS[4]}"/>',
            '    <text x="1019" y="220">More</text>',
            "  </g>",
        ]
    )


def ammo_markup(
    ordered_active: list[Day], timings: list[Timing], duration: float
) -> str:
    if not ordered_active:
        return "  <!-- No active contribution dots: the plant remains idle. -->"

    peas: list[str] = [
        "  <!-- Each moving circle is literally the same dot removed from the calendar. -->",
        '  <g id="plant-uses-every-contribution-dot">',
    ]
    for index, (day, timing) in enumerate(zip(ordered_active, timings), start=1):
        take_key = timing.take / duration
        loaded_key = timing.loaded / duration
        impact_key = timing.impact / duration
        peas.extend(
            [
                f'    <circle id="ammo-{index}" r="{fmt(AMMO_RADIUS)}" fill="{AMMO_COLOR}" opacity="0">',
                f'      <title>{escape(day.date)} contribution dot used as pea {index}</title>',
                f'      <animate attributeName="cx" values="{fmt(day.cx)};{fmt(day.cx)};{PLANT_X};{ZOMBIE_X};{ZOMBIE_X}" '
                f'keyTimes="0;{fmt(take_key)};{fmt(loaded_key)};{fmt(impact_key)};1" calcMode="linear" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
                f'      <animate attributeName="cy" values="{fmt(day.cy)};{fmt(day.cy)};{PLANT_Y};{ZOMBIE_Y};{ZOMBIE_Y}" '
                f'keyTimes="0;{fmt(take_key)};{fmt(loaded_key)};{fmt(impact_key)};1" calcMode="linear" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
                '      <animate attributeName="opacity" values="0;1;0;0" '
                f'keyTimes="0;{fmt(take_key)};{fmt(impact_key)};1" calcMode="discrete" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
                "    </circle>",
            ]
        )
    peas.append("  </g>")
    return "\n".join(peas)


def plant_frame_animation(timings: list[Timing], duration: float) -> str:
    values = ["4"]
    key_times = [0.0]
    frame_offsets = [
        (0.0, "-456"),
        (0.035, "-686"),
        (0.070, "-916"),
        (0.105, "-1146"),
        (0.140, "4"),
    ]
    for timing in timings:
        for offset, frame in frame_offsets:
            key_times.append((timing.loaded + offset) / duration)
            values.append(frame)
    key_times.append(1.0)
    values.append("4")
    return (
        '<animate attributeName="x" '
        f'values="{";".join(values)}" '
        f'keyTimes="{";".join(fmt(value) for value in key_times)}" '
        f'calcMode="discrete" dur="{fmt(duration)}s" repeatCount="indefinite"/>'
    )


def combat_markup(timings: list[Timing], duration: float) -> str:
    if timings:
        health_values = [96]
        health_times = [0.0]
        count = len(timings)
        for index, timing in enumerate(timings, start=1):
            health_times.append(timing.impact / duration)
            health_values.append(round(96 - 88 * index / count, 2))
        health_times.append(1.0)
        health_values.append(8)
        animation = (
            '    <animate attributeName="width" '
            f'values="{";".join(fmt(value) for value in health_values)}" '
            f'keyTimes="{";".join(fmt(value) for value in health_times)}" '
            f'calcMode="discrete" dur="{fmt(duration)}s" repeatCount="indefinite"/>'
        )
    else:
        animation = ""

    return "\n".join(
        [
            "  <!-- One health step per consumed contribution dot. -->",
            '  <rect x="1100" y="48" width="108" height="17" rx="7" fill="#08100d" stroke="#9bb39b" stroke-width="2"/>',
            '  <rect x="1106" y="53" width="96" height="7" rx="3.5" fill="url(#health)">',
            animation,
            "  </rect>",
        ]
    )


def load_days(calendar: dict) -> list[Day]:
    days: list[Day] = []
    for week_index, week in enumerate(calendar["weeks"][-53:]):
        for item in week["contributionDays"]:
            days.append(
                Day(
                    date=item["date"],
                    weekday=int(item["weekday"]),
                    count=int(item["contributionCount"]),
                    level=LEVEL_INDEX[item["contributionLevel"]],
                    week_index=week_index,
                )
            )
    return days


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Turn every active GitHub contribution day into identical pea ammo."
    )
    parser.add_argument("--base-svg", required=True, type=Path)
    parser.add_argument("--out-svg", required=True, type=Path)
    parser.add_argument("--login")
    args = parser.parse_args()

    login = args.login or gh_json("api", "user")["login"]
    payload = gh_json("api", "graphql", "-f", f"query={QUERY}", "-F", f"login={login}")
    calendar = payload["data"]["user"]["contributionsCollection"]["contributionCalendar"]
    days = load_days(calendar)
    ordered_active = sorted(
        (day for day in days if day.count > 0), key=lambda day: day.snake_order
    )
    timings, duration = timeline(len(ordered_active))
    total = int(calendar["totalContributions"])

    source = args.base_svg.read_text(encoding="utf-8")
    source = re.sub(
        r'  <!-- Contribution grid remains vector and crisp -->.*?(?=  <path d="M0 228c)',
        calendar_markup(days, ordered_active, timings, duration, login, total) + "\n\n",
        source,
        flags=re.DOTALL,
    )
    source = source.replace(
        "  <!-- ImageGen sprite sheets embedded as data URIs; SVG switches frames discretely -->",
        ammo_markup(ordered_active, timings, duration)
        + "\n\n  <!-- ImageGen sprite sheets embedded as data URIs; SVG switches frames discretely -->",
    )
    source = re.sub(
        r'  <!-- Health and hits stay deterministic -->.*?(?=  <rect x="1\.5")',
        combat_markup(timings, duration) + "\n\n",
        source,
        flags=re.DOTALL,
    )
    source = re.sub(
        r'<animate attributeName="x" values="4;-226;-456;-686;-916;-1146" calcMode="discrete" dur="2s" repeatCount="indefinite"/>',
        plant_frame_animation(timings, duration),
        source,
        count=1,
    )
    source = re.sub(
        r'<desc id="desc">.*?</desc>',
        f'<desc id="desc">@{escape(login)} has {total} contributions across {len(ordered_active)} active-day dots. Every identical green dot is loaded into the plant and fired at the zombie before the loop resets.</desc>',
        source,
    )

    args.out_svg.write_text(source, encoding="utf-8")
    print(
        json.dumps(
            {
                "login": login,
                "totalContributions": total,
                "ammoDots": len(ordered_active),
                "cycleSeconds": duration,
                "firstDot": ordered_active[0].date if ordered_active else None,
                "lastDot": ordered_active[-1].date if ordered_active else None,
                "output": str(args.out_svg),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
