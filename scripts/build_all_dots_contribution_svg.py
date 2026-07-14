from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from html import escape
from pathlib import Path


QUERY = r"""
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
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

PIXEL_FONT = {
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "C": ("01111", "10000", "10000", "10000", "10000", "10000", "01111"),
    "D": ("11110", "10001", "10001", "10001", "10001", "10001", "11110"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "F": ("11111", "10000", "10000", "11110", "10000", "10000", "10000"),
    "G": ("01111", "10000", "10000", "10111", "10001", "10001", "01111"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "I": ("11111", "00100", "00100", "00100", "00100", "00100", "11111"),
    "J": ("00111", "00010", "00010", "00010", "10010", "10010", "01100"),
    "K": ("10001", "10010", "10100", "11000", "10100", "10010", "10001"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "M": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
    "N": ("10001", "11001", "10101", "10011", "10001", "10001", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "P": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "Q": ("01110", "10001", "10001", "10001", "10101", "10010", "01101"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "U": ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
    "V": ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
    "W": ("10001", "10001", "10001", "10101", "10101", "10101", "01010"),
    "X": ("10001", "10001", "01010", "00100", "01010", "10001", "10001"),
    "Y": ("10001", "10001", "01010", "00100", "00100", "00100", "00100"),
    "Z": ("11111", "00001", "00010", "00100", "01000", "10000", "11111"),
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "10000", "11110", "00001", "00001", "11110"),
    "6": ("01110", "10000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00001", "01110"),
    "/": ("00001", "00010", "00010", "00100", "01000", "01000", "10000"),
    "-": ("00000", "00000", "00000", "11111", "00000", "00000", "00000"),
    " ": ("00000",) * 7,
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
INTRO_TIME = 1.20
LOAD_TIME = 0.45
FLIGHT_TIME = 0.80
MAX_SHOT_INTERVAL = 0.55
OUTCOME_TIME = 4.0
RESET_TIME = 1.5
SUCCESS_TRANSLATE = -620.0
FAILURE_TRANSLATE = -865.0


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
    impact_x: float
    impact_y: float


def gh_json(*args: str) -> dict:
    result = subprocess.run(
        ["gh", *args],
        check=False,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )
    if result.returncode:
        error = result.stderr.strip() or result.stdout.strip() or "unknown gh error"
        raise RuntimeError(f"gh {' '.join(args[:2])} failed: {error}")
    return json.loads(result.stdout)


def fmt(value: float) -> str:
    return f"{value:.5f}".rstrip("0").rstrip(".")


def key(time_value: float, duration: float) -> str:
    return fmt(min(1.0, max(0.0, time_value / duration)))


def timeline(active_count: int, battle_seconds: float, zombie_translate: float) -> tuple[list[Timing], float, float, float]:
    battle_end = INTRO_TIME + battle_seconds
    outcome_end = battle_end + OUTCOME_TIME
    duration = outcome_end + RESET_TIME
    shot_start = INTRO_TIME + 0.45
    available = max(0.1, battle_seconds - LOAD_TIME - FLIGHT_TIME - 0.75)
    interval = 0.0
    if active_count > 1:
        interval = min(MAX_SHOT_INTERVAL, available / (active_count - 1))

    timings: list[Timing] = []
    for index in range(active_count):
        take = shot_start + index * interval
        loaded = take + LOAD_TIME
        impact = loaded + FLIGHT_TIME
        progress = min(1.0, max(0.0, impact / battle_end))
        impact_x = ZOMBIE_X + zombie_translate * progress
        impact_y = ZOMBIE_Y + ((index % 3) - 1) * 7
        timings.append(
            Timing(
                take=take,
                loaded=loaded,
                impact=impact,
                impact_x=impact_x,
                impact_y=impact_y,
            )
        )
    return timings, duration, battle_end, outcome_end


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
    total: int,
    window_days: int,
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
        cells.extend(
            [
                f'    <rect x="{fmt(day.x)}" y="{fmt(day.y)}" width="{CELL_SIZE}" height="{CELL_SIZE}" rx="2" fill="{fill}">',
                f'      <title>{title}</title>',
                '      <animate attributeName="opacity" values="1;1;0;0;1" '
                f'keyTimes="0;{key(timing.take - 0.02, duration)};{key(timing.take, duration)};{key(duration - 0.02, duration)};1" '
                f'calcMode="discrete" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
                "    </rect>",
            ]
        )

    period_label = "the last year" if window_days == 365 else f"the last {window_days} days"
    return "\n".join(
        [
            "  <!-- GitHub Contribution Calendar UI: 11px cells with 4px border spacing. -->",
            f'  <text x="190" y="77" fill="#c9d1d9" font-family="-apple-system, BlinkMacSystemFont, Segoe UI, sans-serif" font-size="13">{total} contributions in {period_label}</text>',
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


def ammo_markup(ordered_active: list[Day], timings: list[Timing], duration: float) -> str:
    if not ordered_active:
        return "  <!-- No active contribution dots: the plant remains idle. -->"

    peas: list[str] = [
        "  <!-- Every non-empty contribution cell becomes one equally bright pea. -->",
        '  <g id="plant-uses-every-contribution-dot" filter="url(#glow)">',
    ]
    for index, (day, timing) in enumerate(zip(ordered_active, timings), start=1):
        peas.extend(
            [
                f'    <circle id="ammo-{index}" r="{fmt(AMMO_RADIUS)}" fill="{AMMO_COLOR}" stroke="#006d32" stroke-width="1" opacity="0">',
                f'      <title>{escape(day.date)}: {day.count} contributions loaded as pea {index}</title>',
                f'      <animate attributeName="cx" values="{fmt(day.cx)};{fmt(day.cx)};{PLANT_X};{fmt(timing.impact_x)};{fmt(timing.impact_x)}" '
                f'keyTimes="0;{key(timing.take, duration)};{key(timing.loaded, duration)};{key(timing.impact, duration)};1" calcMode="linear" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
                f'      <animate attributeName="cy" values="{fmt(day.cy)};{fmt(day.cy)};{PLANT_Y};{fmt(timing.impact_y)};{fmt(timing.impact_y)}" '
                f'keyTimes="0;{key(timing.take, duration)};{key(timing.loaded, duration)};{key(timing.impact, duration)};1" calcMode="linear" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
                '      <animate attributeName="opacity" values="0;1;1;0;0" '
                f'keyTimes="0;{key(timing.take, duration)};{key(timing.loaded, duration)};{key(timing.impact, duration)};1" calcMode="discrete" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
                "    </circle>",
            ]
        )
    peas.append("  </g>")
    return "\n".join(peas)


def plant_group_open(success: bool, battle_end: float, outcome_end: float, duration: float) -> str:
    lines = [
        '  <g id="plant-sprite" clip-path="url(#plant-window)" filter="url(#shadow)" style="image-rendering:pixelated">'
    ]
    if not success:
        bite1 = battle_end + 0.45
        bite2 = battle_end + 1.00
        bite3 = battle_end + 1.55
        gone = battle_end + 2.05
        lines.extend(
            [
                '    <animateTransform attributeName="transform" type="translate" '
                'values="0 0;0 0;-5 0;5 0;-6 1;6 1;-4 2;4 2;0 0;0 0" '
                f'keyTimes="0;{key(battle_end, duration)};{key(bite1, duration)};{key(bite1 + 0.16, duration)};{key(bite2, duration)};{key(bite2 + 0.16, duration)};{key(bite3, duration)};{key(bite3 + 0.16, duration)};{key(gone, duration)};1" '
                f'dur="{fmt(duration)}s" repeatCount="indefinite"/>',
                '    <animate attributeName="opacity" values="1;1;.72;.72;.38;.38;0;0;1" '
                f'keyTimes="0;{key(bite1, duration)};{key(bite1 + 0.18, duration)};{key(bite2, duration)};{key(bite2 + 0.18, duration)};{key(bite3, duration)};{key(gone, duration)};{key(outcome_end, duration)};1" '
                f'calcMode="discrete" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
            ]
        )
    return "\n".join(lines)


def zombie_animation(success: bool, battle_end: float, outcome_end: float, duration: float) -> str:
    if success:
        fall1 = battle_end + 0.55
        fall2 = battle_end + 1.35
        return "\n".join(
            [
                '    <animateTransform attributeName="transform" type="translate" '
                f'values="0 0;{fmt(SUCCESS_TRANSLATE)} 0;-642 12;-660 72;-660 72;0 0" '
                f'keyTimes="0;{key(battle_end, duration)};{key(fall1, duration)};{key(fall2, duration)};{key(outcome_end, duration)};1" '
                f'dur="{fmt(duration)}s" repeatCount="indefinite"/>',
                '    <animate attributeName="opacity" values="1;1;1;0;0;1" '
                f'keyTimes="0;{key(battle_end, duration)};{key(fall1, duration)};{key(fall2, duration)};{key(outcome_end, duration)};1" '
                f'dur="{fmt(duration)}s" repeatCount="indefinite"/>',
            ]
        )

    bite1 = battle_end + 0.45
    bite2 = battle_end + 1.00
    bite3 = battle_end + 1.55
    return (
        '    <animateTransform attributeName="transform" type="translate" '
        f'values="0 0;{fmt(FAILURE_TRANSLATE)} 0;-845 0;-865 0;-845 0;-865 0;-865 0;0 0" '
        f'keyTimes="0;{key(battle_end, duration)};{key(bite1, duration)};{key(bite2, duration)};{key(bite3, duration)};{key(bite3 + 0.28, duration)};{key(outcome_end, duration)};1" '
        f'dur="{fmt(duration)}s" repeatCount="indefinite"/>'
    )


def zombie_shadow(success: bool, battle_end: float, outcome_end: float, duration: float) -> str:
    end_translate = SUCCESS_TRANSLATE if success else FAILURE_TRANSLATE
    end_x = 1150 + end_translate
    values = f"1150;{fmt(end_x)};{fmt(end_x)};1150"
    return (
        '<ellipse cy="247" rx="72" ry="11" fill="#020a09" opacity=".55">'
        f'<animate attributeName="cx" values="{values}" keyTimes="0;{key(battle_end, duration)};{key(outcome_end, duration)};1" '
        f'dur="{fmt(duration)}s" repeatCount="indefinite"/>'
        '</ellipse>'
    )


def health_markup(
    ordered_active: list[Day],
    timings: list[Timing],
    total: int,
    target: int,
    success: bool,
    battle_end: float,
    outcome_end: float,
    duration: float,
) -> str:
    actual_sum = sum(day.count for day in ordered_active)
    scale = total / actual_sum if actual_sum else 0.0
    effective_target = max(1.0, float(total if success and total > 0 else target))
    cumulative = 0.0
    widths = [96.0]
    times = [0.0]
    for day, timing in zip(ordered_active, timings):
        cumulative += day.count * scale
        widths.append(max(0.0, 96.0 * (1.0 - cumulative / effective_target)))
        times.append(timing.impact)
    final_width = widths[-1]
    times.extend([battle_end, outcome_end, duration])
    widths.extend([final_width, final_width, 96.0])

    impacts: list[str] = []
    for index, timing in enumerate(timings, start=1):
        before = max(0.0, timing.impact - 0.04)
        after = min(duration, timing.impact + 0.15)
        impacts.extend(
            [
                f'  <circle cx="{fmt(timing.impact_x)}" cy="{fmt(timing.impact_y)}" r="12" fill="#b7ff72" opacity="0" filter="url(#glow)">',
                '    <animate attributeName="opacity" values="0;0;1;0;0" '
                f'keyTimes="0;{key(before, duration)};{key(timing.impact, duration)};{key(after, duration)};1" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
                '    <animate attributeName="r" values="2;2;13;2;2" '
                f'keyTimes="0;{key(before, duration)};{key(timing.impact, duration)};{key(after, duration)};1" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
                "  </circle>",
            ]
        )

    return "\n".join(
        [
            "  <!-- Health represents progress toward the configurable contribution target. -->",
            f'  <text x="1098" y="42" fill="#c9d1d9" font-family="ui-monospace, SFMono-Regular, Consolas, monospace" font-size="11">GOAL {total} / {target}</text>',
            '  <rect x="1100" y="48" width="108" height="17" rx="7" fill="#08100d" stroke="#9bb39b" stroke-width="2"/>',
            '  <rect x="1106" y="53" width="96" height="7" rx="3.5" fill="url(#health)">',
            '    <animate attributeName="width" '
            f'values="{";".join(fmt(value) for value in widths)}" '
            f'keyTimes="{";".join(key(value, duration) for value in times)}" '
            f'calcMode="discrete" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
            "  </rect>",
            *impacts,
        ]
    )


def message_points(line: str, y: float, step: float = 5.0) -> list[tuple[float, float, int, int]]:
    advance = step * 6
    width = max(0.0, len(line) * advance - step)
    start_x = 635.5 - width / 2
    points: list[tuple[float, float, int, int]] = []
    for char_index, char in enumerate(line):
        glyph = PIXEL_FONT.get(char.upper(), PIXEL_FONT[" "])
        for row_index, row in enumerate(glyph):
            for col_index, bit in enumerate(row):
                if bit == "1":
                    points.append(
                        (
                            start_x + char_index * advance + col_index * step,
                            y + row_index * step,
                            row_index,
                            col_index + char_index * 6,
                        )
                    )
    return points


def victory_message(
    ordered_active: list[Day], total: int, target: int, battle_end: float, outcome_end: float, duration: float
) -> str:
    lines = ["CRITICAL MASS REACHED", f"{total} OF {target} CONTRIBS", "BRAIN SAVED"]
    palette = ("#7ee787", "#39d353", "#39d353", "#26a641")
    dots: list[str] = []
    dot_index = 0
    for line_index, (line, y) in enumerate(zip(lines, (97.0, 141.0, 185.0))):
        for x, target_y, row, col in message_points(line, y):
            source = ordered_active[dot_index % len(ordered_active)] if ordered_active else None
            source_x = source.cx if source else PLANT_X
            source_y = source.cy if source else PLANT_Y
            start = battle_end + 0.45 + (dot_index % 28) * 0.022
            formed = start + 0.82
            color = palette[(line_index + row + col) % len(palette)]
            dots.extend(
                [
                    f'    <circle cx="{fmt(source_x)}" cy="{fmt(source_y)}" r="2.15" fill="{color}" stroke="#0e4429" stroke-width=".45" opacity="0">',
                    f'      <animate attributeName="cx" values="{fmt(source_x)};{fmt(source_x)};{fmt(x)};{fmt(x)};{fmt(x)}" keyTimes="0;{key(start, duration)};{key(formed, duration)};{key(outcome_end, duration)};1" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
                    f'      <animate attributeName="cy" values="{fmt(source_y)};{fmt(source_y)};{fmt(target_y)};{fmt(target_y)};{fmt(target_y)}" keyTimes="0;{key(start, duration)};{key(formed, duration)};{key(outcome_end, duration)};1" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
                    '      <animate attributeName="opacity" values="0;0;1;1;0" '
                    f'keyTimes="0;{key(start, duration)};{key(formed, duration)};{key(outcome_end, duration)};1" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
                    "    </circle>",
                ]
            )
            dot_index += 1
    return "\n".join(dots)


def failure_message(total: int, target: int, battle_end: float, outcome_end: float, duration: float) -> str:
    lines = ["TARGET MISSED", f"{total} OF {target} CONTRIBS", "ZOMBIE ATE YOUR BRAIN"]
    palette = ("#ff7b72", "#f85149", "#f85149", "#da3633")
    dots: list[str] = []
    dot_index = 0
    for line_index, (line, y) in enumerate(zip(lines, (97.0, 141.0, 185.0))):
        for x, target_y, row, col in message_points(line, y):
            start = battle_end + 2.05 + (dot_index % 22) * 0.024
            settled = start + 0.36
            color = palette[(line_index + row + col) % len(palette)]
            dots.extend(
                [
                    f'    <rect x="{fmt(x - 2)}" y="{fmt(target_y - 12)}" width="4" height="4" rx=".6" fill="{color}" stroke="#6e0f14" stroke-width=".45" opacity="0">',
                    f'      <animate attributeName="y" values="{fmt(target_y - 12)};{fmt(target_y - 12)};{fmt(target_y)};{fmt(target_y)};{fmt(target_y)}" keyTimes="0;{key(start, duration)};{key(settled, duration)};{key(outcome_end, duration)};1" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
                    '      <animate attributeName="opacity" values="0;0;1;1;0" '
                    f'keyTimes="0;{key(start, duration)};{key(settled, duration)};{key(outcome_end, duration)};1" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
                    "    </rect>",
                ]
            )
            dot_index += 1

    drip_specs = ((310, 218, 13), (407, 213, 8), (568, 217, 15), (731, 214, 10), (892, 216, 14), (968, 211, 7))
    for index, (x, y, height) in enumerate(drip_specs):
        start = battle_end + 2.45 + index * 0.08
        dots.extend(
            [
                f'    <rect x="{x}" y="{y}" width="3" height="0" rx="1.5" fill="#b62324" opacity="0">',
                f'      <animate attributeName="height" values="0;0;{height};{height};0" keyTimes="0;{key(start, duration)};{key(start + 0.55, duration)};{key(outcome_end, duration)};1" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
                f'      <animate attributeName="opacity" values="0;0;.9;.9;0" keyTimes="0;{key(start, duration)};{key(start + 0.2, duration)};{key(outcome_end, duration)};1" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
                "    </rect>",
            ]
        )
    return "\n".join(dots)


def eaten_particles(battle_end: float, outcome_end: float, duration: float) -> str:
    particles: list[str] = ['  <g id="eaten-plant-pixels">']
    specs = (
        (105, 145, -35, -22, "#7ee787"),
        (125, 132, 18, -31, "#39d353"),
        (145, 153, 39, -12, "#26a641"),
        (109, 178, -29, 20, "#39d353"),
        (137, 184, 31, 26, "#0e4429"),
        (154, 165, 47, 8, "#7ee787"),
        (119, 204, -14, 27, "#26a641"),
        (149, 211, 26, 18, "#39d353"),
    )
    start = battle_end + 0.72
    for index, (x, y, dx, dy, color) in enumerate(specs):
        launch = start + index * 0.045
        particles.extend(
            [
                f'    <rect x="{x}" y="{y}" width="6" height="6" rx="1" fill="{color}" opacity="0">',
                f'      <animateTransform attributeName="transform" type="translate" values="0 0;0 0;{dx} {dy};{dx} {dy}" keyTimes="0;{key(launch, duration)};{key(launch + 0.72, duration)};1" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
                f'      <animate attributeName="opacity" values="0;0;1;0;0" keyTimes="0;{key(launch, duration)};{key(launch + 0.08, duration)};{key(launch + 0.78, duration)};1" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
                "    </rect>",
            ]
        )
    particles.append("  </g>")
    return "\n".join(particles)


def outcome_markup(
    ordered_active: list[Day],
    total: int,
    target: int,
    success: bool,
    battle_end: float,
    outcome_end: float,
    duration: float,
) -> str:
    accent = "#39d353" if success else "#f85149"
    background = "#07140d" if success else "#19090d"
    message = (
        victory_message(ordered_active, total, target, battle_end, outcome_end, duration)
        if success
        else failure_message(total, target, battle_end, outcome_end, duration)
    )
    overlay_start = battle_end + (0.40 if success else 1.95)
    parts = [
        f'  <rect x="190" y="84" width="891" height="143" rx="6" fill="{background}" stroke="{accent}" stroke-width="2" opacity="0">',
        '    <animate attributeName="opacity" values="0;0;.96;.96;0" '
        f'keyTimes="0;{key(overlay_start, duration)};{key(overlay_start + 0.18, duration)};{key(outcome_end, duration)};1" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
        "  </rect>",
    ]
    if not success:
        parts.append(eaten_particles(battle_end, outcome_end, duration))
    parts.extend([f'  <g id="{"victory" if success else "failure"}-pixel-message">', message, "  </g>"])
    return "\n".join(parts)


def load_days(calendar: dict) -> list[Day]:
    weeks = calendar["weeks"][-53:]
    week_offset = max(0, 53 - len(weeks))
    days: list[Day] = []
    for relative_week, week in enumerate(weeks):
        for item in week["contributionDays"]:
            days.append(
                Day(
                    date=item["date"],
                    weekday=int(item["weekday"]),
                    count=int(item["contributionCount"]),
                    level=LEVEL_INDEX[item["contributionLevel"]],
                    week_index=week_offset + relative_week,
                )
            )
    return days


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Turn contribution-day dots into a configurable zombie brain-defense challenge."
    )
    parser.add_argument("--base-svg", required=True, type=Path)
    parser.add_argument("--out-svg", required=True, type=Path)
    parser.add_argument("--login")
    parser.add_argument(
        "--target-contributions",
        type=positive_int,
        default=positive_int(os.getenv("TARGET_CONTRIBUTIONS", "60")),
    )
    parser.add_argument(
        "--window-days",
        type=positive_int,
        default=positive_int(os.getenv("WINDOW_DAYS", "365")),
    )
    parser.add_argument(
        "--battle-seconds",
        type=float,
        default=float(os.getenv("BATTLE_SECONDS", "18")),
    )
    parser.add_argument("--force-total", type=int, help="Preview-only override for the displayed total and outcome.")
    args = parser.parse_args()

    if args.window_days > 365:
        parser.error("--window-days must be between 1 and 365")
    if args.battle_seconds < 6:
        parser.error("--battle-seconds must be at least 6")
    if args.force_total is not None and args.force_total < 0:
        parser.error("--force-total cannot be negative")

    login = args.login or gh_json("api", "user")["login"]
    today = datetime.now(timezone.utc).date()
    from_date = today - timedelta(days=args.window_days - 1)
    from_iso = f"{from_date.isoformat()}T00:00:00Z"
    to_iso = f"{today.isoformat()}T23:59:59Z"
    payload = gh_json(
        "api",
        "graphql",
        "-f",
        f"query={QUERY}",
        "-F",
        f"login={login}",
        "-F",
        f"from={from_iso}",
        "-F",
        f"to={to_iso}",
    )
    calendar = payload["data"]["user"]["contributionsCollection"]["contributionCalendar"]
    days = load_days(calendar)
    ordered_active = sorted(
        (day for day in days if day.count > 0), key=lambda day: day.snake_order
    )
    api_total = int(calendar["totalContributions"])
    total = args.force_total if args.force_total is not None else api_total
    success = total >= args.target_contributions
    zombie_translate = SUCCESS_TRANSLATE if success else FAILURE_TRANSLATE
    timings, duration, battle_end, outcome_end = timeline(
        len(ordered_active), args.battle_seconds, zombie_translate
    )

    source = args.base_svg.read_text(encoding="utf-8")
    source = re.sub(
        r'  <!-- Contribution grid remains vector and crisp -->.*?(?=  <path d="M0 228c)',
        calendar_markup(
            days,
            ordered_active,
            timings,
            duration,
            total,
            args.window_days,
        )
        + "\n\n",
        source,
        flags=re.DOTALL,
    )
    source = source.replace(
        "  <!-- ImageGen sprite sheets embedded as data URIs; SVG switches frames discretely -->",
        ammo_markup(ordered_active, timings, duration)
        + "\n\n  <!-- ImageGen sprite sheets embedded as data URIs; SVG switches frames discretely -->",
    )
    source = source.replace(
        '  <g clip-path="url(#plant-window)" filter="url(#shadow)" style="image-rendering:pixelated">',
        plant_group_open(success, battle_end, outcome_end, duration),
        1,
    )
    source = re.sub(
        r'<animate attributeName="x" values="4;-226;-456;-686;-916;-1146" calcMode="discrete" dur="2s" repeatCount="indefinite"/>',
        '<animate attributeName="x" values="4;-226;-456;-686;-916;-1146" calcMode="discrete" dur="1.05s" repeatCount="indefinite"/>',
        source,
        count=1,
    )
    source = source.replace(
        '<ellipse cx="1150" cy="247" rx="72" ry="11" fill="#020a09" opacity=".55"/>',
        zombie_shadow(success, battle_end, outcome_end, duration),
        1,
    )
    source = re.sub(
        r'    <animateTransform attributeName="transform" type="translate" values="8 0;-12 0;8 0" keyTimes="0;.52;1" dur="6s" repeatCount="indefinite"/>',
        zombie_animation(success, battle_end, outcome_end, duration),
        source,
        count=1,
    )
    source = re.sub(
        r'  <!-- Health and hits stay deterministic -->.*?(?=  <rect x="1\.5")',
        health_markup(
            ordered_active,
            timings,
            total,
            args.target_contributions,
            success,
            battle_end,
            outcome_end,
            duration,
        )
        + "\n\n"
        + outcome_markup(
            ordered_active,
            total,
            args.target_contributions,
            success,
            battle_end,
            outcome_end,
            duration,
        )
        + "\n\n",
        source,
        flags=re.DOTALL,
    )
    source = re.sub(
        r'<title id="title">.*?</title>',
        f'<title id="title">Contribution brain defense: {total} of {args.target_contributions}</title>',
        source,
    )
    source = re.sub(
        r'<desc id="desc">.*?</desc>',
        f'<desc id="desc">@{escape(login)} has {total} contributions in the last {args.window_days} days against a target of {args.target_contributions}. The zombie {"is defeated and the brain is saved" if success else "reaches the plant and eats the brain"}. Only contribution dates and counts are used.</desc>',
        source,
    )

    args.out_svg.parent.mkdir(parents=True, exist_ok=True)
    args.out_svg.write_text(source, encoding="utf-8")
    print(
        json.dumps(
            {
                "login": login,
                "apiTotalContributions": api_total,
                "displayedContributions": total,
                "targetContributions": args.target_contributions,
                "windowDays": args.window_days,
                "battleSeconds": args.battle_seconds,
                "outcome": "success" if success else "failure",
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
