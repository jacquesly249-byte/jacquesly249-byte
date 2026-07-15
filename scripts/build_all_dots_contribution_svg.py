from __future__ import annotations

import argparse
import base64
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
# The original Peashooter fires roughly once every 1.5 seconds. When there are
# more contribution dots than fit at that cadence, the interval compresses so
# every dot is still consumed before contact.
PVZ_SHOT_INTERVAL = 1.50
OUTCOME_TIME = 5.0
RESET_TIME = 1.5
SUCCESS_TRANSLATE = -620.0
FAILURE_TRANSLATE = -895.0
ARM_LOSS_RATIO = 0.50
CRITICAL_RATIO = 0.82
HEAD_LOSS_RATIO = 0.88
MIN_POST_HEAD_HITS = 3
# Sprite sheets use different canvas sizes and transparent padding, so matching
# their outer <image> boxes makes the character visibly change size.  These
# placements are derived from the alpha bounds of the neutral reference poses:
#
#   original frame 0: 164 x 222 at 240 / 256 display scale
#   generated frame 0: 183 px tall on a 240 x 230 canvas
#   dismember frame 0: 258 px tall on a 457 x 430 canvas
#
# Every reference pose therefore lands at the original zombie's visible height
# (208.125 px), visual centre (x=1150), and foot baseline (y=252.625).
ZOMBIE_REFERENCE_HEIGHT = 222 * 240 / 256
ZOMBIE_REFERENCE_CENTER_X = 1150.0
ZOMBIE_REFERENCE_BASELINE_Y = 22 + 246 * 240 / 256

GENERATED_ZOMBIE_SCALE = ZOMBIE_REFERENCE_HEIGHT / 183
GENERATED_ZOMBIE_Y = ZOMBIE_REFERENCE_BASELINE_Y - 212 * GENERATED_ZOMBIE_SCALE
GENERATED_ZOMBIE_WIDTH = 240 * GENERATED_ZOMBIE_SCALE
GENERATED_ZOMBIE_HEIGHT = 230 * GENERATED_ZOMBIE_SCALE
DAMAGED_WALK_ZOMBIE_X = ZOMBIE_REFERENCE_CENTER_X - 124.5 * GENERATED_ZOMBIE_SCALE
CRITICAL_WALK_ZOMBIE_X = ZOMBIE_REFERENCE_CENTER_X - 120.0 * GENERATED_ZOMBIE_SCALE
HEADLESS_ZOMBIE_X = ZOMBIE_REFERENCE_CENTER_X - 124.5 * GENERATED_ZOMBIE_SCALE
INTACT_BITE_ZOMBIE_X = ZOMBIE_REFERENCE_CENTER_X - 128.5 * GENERATED_ZOMBIE_SCALE
DAMAGED_BITE_ZOMBIE_X = ZOMBIE_REFERENCE_CENTER_X - 137.5 * GENERATED_ZOMBIE_SCALE
CRITICAL_BITE_ZOMBIE_X = ZOMBIE_REFERENCE_CENTER_X - 138.0 * GENERATED_ZOMBIE_SCALE

DISMEMBER_ZOMBIE_SCALE = ZOMBIE_REFERENCE_HEIGHT / 258
DISMEMBER_ZOMBIE_X = ZOMBIE_REFERENCE_CENTER_X - 228.5 * DISMEMBER_ZOMBIE_SCALE
DISMEMBER_ZOMBIE_Y = ZOMBIE_REFERENCE_BASELINE_Y - 366 * DISMEMBER_ZOMBIE_SCALE
DISMEMBER_ZOMBIE_WIDTH = 457 * DISMEMBER_ZOMBIE_SCALE
DISMEMBER_ZOMBIE_HEIGHT = 430 * DISMEMBER_ZOMBIE_SCALE

# Each bite is staged as anticipation, snap, hold, and recovery. The damage
# lands on the snap so the missing plant chunks read as a direct consequence.
BITE_PHASES = (
    (0.34, 0.54, 0.68, 0.91),
    (1.06, 1.26, 1.40, 1.63),
    (1.78, 1.98, 2.12, 2.35),
)
BLACKOUT_OFFSET = 2.52


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


@dataclass(frozen=True)
class CombatPhases:
    arm_loss: float | None
    critical: float | None
    head_loss: float | None
    lethal: float | None
    failure_state: str


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


def image_data_uri(path: Path) -> str:
    mime_by_suffix = {".gif": "image/gif", ".png": "image/png", ".webp": "image/webp"}
    mime = mime_by_suffix[path.suffix.lower()]
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def timeline(active_count: int, battle_seconds: float, zombie_translate: float) -> tuple[list[Timing], float, float, float]:
    battle_end = INTRO_TIME + battle_seconds
    outcome_end = battle_end + OUTCOME_TIME
    duration = outcome_end + RESET_TIME
    earliest_take = INTRO_TIME + 0.45
    latest_take = battle_end - LOAD_TIME - FLIGHT_TIME
    interval = 0.0
    first_take = latest_take
    if active_count > 1:
        available = max(0.1, latest_take - earliest_take)
        interval = min(PVZ_SHOT_INTERVAL, available / (active_count - 1))
        first_take = latest_take - interval * (active_count - 1)

    timings: list[Timing] = []
    for index in range(active_count):
        take = first_take + index * interval
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


def combat_phases(
    ordered_active: list[Day],
    timings: list[Timing],
    total: int,
    target: int,
    success: bool,
    battle_end: float,
) -> CombatPhases:
    """Map cumulative contribution damage to PvZ-like visible degradation."""
    actual_sum = sum(day.count for day in ordered_active)
    scale = total / actual_sum if actual_sum else 0.0
    damage_budget = float(total if success and total > 0 else target)
    cumulative = 0.0
    arm_loss: float | None = None
    critical: float | None = None
    arm_loss_index: int | None = None
    head_loss_candidate_index: int | None = None

    for index, (day, timing) in enumerate(zip(ordered_active, timings)):
        cumulative += day.count * scale
        ratio = cumulative / max(1.0, damage_budget)
        if arm_loss is None and ratio >= ARM_LOSS_RATIO:
            arm_loss = timing.impact
            arm_loss_index = index
        if critical is None and ratio >= CRITICAL_RATIO:
            critical = timing.impact
        if head_loss_candidate_index is None and ratio >= HEAD_LOSS_RATIO:
            head_loss_candidate_index = index

    head_loss: float | None = None
    if success and timings:
        latest_head_index = max(0, len(timings) - MIN_POST_HEAD_HITS - 1)
        candidate_index = (
            head_loss_candidate_index
            if head_loss_candidate_index is not None
            else latest_head_index
        )
        head_index = min(candidate_index, latest_head_index)
        if arm_loss_index is not None and len(timings) > MIN_POST_HEAD_HITS + 1:
            head_index = max(arm_loss_index + 1, head_index)
            head_index = min(head_index, latest_head_index)
        head_loss = timings[head_index].impact

    progress = total / max(1.0, float(target))
    failure_state = (
        "critical"
        if progress >= CRITICAL_RATIO
        else "damaged"
        if progress >= ARM_LOSS_RATIO
        else "intact"
    )
    lethal = (timings[-1].impact if timings else battle_end) if success else None
    return CombatPhases(
        arm_loss=arm_loss,
        critical=critical,
        head_loss=head_loss,
        lethal=lethal,
        failure_state=failure_state,
    )


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
    board_empty_at: float,
    duration: float,
    total: int,
    window_days: int,
) -> str:
    timing_by_date = {day.date: timing for day, timing in zip(ordered_active, timings)}
    shot_index_by_date = {day.date: index for index, day in enumerate(ordered_active, start=1)}
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
        pulse_peak = timing.take + 0.10
        pulse_squash = timing.take + 0.20
        pulse_settle = timing.take + 0.30
        fade_start = timing.loaded - 0.08
        pulse_times = (
            0.0,
            timing.take,
            pulse_peak,
            pulse_squash,
            pulse_settle,
            fade_start,
            timing.loaded,
            duration - 0.02,
            duration,
        )
        pulse_keys = ";".join(key(moment, duration) for moment in pulse_times)
        cells.extend(
            [
                f'    <g id="contribution-ammo-{day.date}" transform="translate({fmt(day.cx)} {fmt(day.cy)})">',
                f'      <title>{title}; pulses in place while the Peashooter prepares shot {shot_index_by_date[day.date]}</title>',
                '      <g>',
                f'        <rect x="{-CELL_SIZE / 2}" y="{-CELL_SIZE / 2}" width="{CELL_SIZE}" height="{CELL_SIZE}" rx="2" fill="{fill}" stroke="{AMMO_COLOR}" stroke-width="1">',
                '          <animate attributeName="opacity" values="1;1;1;1;1;1;0;0;1" '
                f'keyTimes="{pulse_keys}" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
                '          <animate attributeName="stroke-opacity" values="0;0;1;.65;.28;0;0;0;0" '
                f'keyTimes="{pulse_keys}" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
                "        </rect>",
                "      </g>",
                '      <g>',
                '        <animateTransform attributeName="transform" type="scale" '
                'values=".8;.8;1.55;2.05;2.3;2.3;2.3;2.3;.8" '
                f'keyTimes="{pulse_keys}" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
                f'        <circle r="{fmt(CELL_SIZE / 2 + 1)}" fill="none" stroke="{AMMO_COLOR}" stroke-width="1.5" opacity="0">',
                '          <animate attributeName="opacity" values="0;0;.82;.32;0;0;0;0;0" '
                f'keyTimes="{pulse_keys}" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
                "        </circle>",
                "      </g>",
                "    </g>",
            ]
        )

    legend_swatches = [
        f'    <rect x="946" y="211" width="10" height="10" rx="2" fill="{GITHUB_DARK_COLORS[0]}"/>'
    ]
    for level, x in enumerate((960, 974, 988, 1002), start=1):
        color = GITHUB_DARK_COLORS[level]
        empty = GITHUB_DARK_COLORS[0]
        legend_swatches.extend(
            [
                f'    <rect x="{x}" y="211" width="10" height="10" rx="2" fill="{color}">',
                f'      <animate attributeName="fill" values="{color};{color};{empty};{empty};{color}" '
                f'keyTimes="0;{key(board_empty_at - 0.02, duration)};{key(board_empty_at, duration)};{key(duration - 0.02, duration)};1" '
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
            *legend_swatches,
            '    <text x="1019" y="220">More</text>',
            "  </g>",
        ]
    )


def ammo_markup(ordered_active: list[Day], timings: list[Timing], duration: float) -> str:
    if not ordered_active:
        return "  <!-- No active contribution dots: the plant remains idle. -->"

    peas: list[str] = [
        "  <!-- Contribution cells pulse in place; peas are born only at the muzzle. -->",
        '  <g id="plant-uses-every-contribution-dot" filter="url(#glow)">',
    ]
    for index, (day, timing) in enumerate(zip(ordered_active, timings), start=1):
        charge_peak = timing.take + 0.20
        charge_settle = timing.loaded - 0.04
        peas.extend(
            [
                f'    <circle id="muzzle-charge-{index}" cx="{PLANT_X}" cy="{PLANT_Y}" r="2" fill="none" stroke="{AMMO_COLOR}" stroke-width="1.5" opacity="0">',
                '      <animate attributeName="r" values="2;2;8;5.5;5.5;2" '
                f'keyTimes="0;{key(timing.take, duration)};{key(charge_peak, duration)};{key(charge_settle, duration)};{key(timing.loaded, duration)};1" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
                '      <animate attributeName="opacity" values="0;0;.72;1;0;0" '
                f'keyTimes="0;{key(timing.take, duration)};{key(charge_peak, duration)};{key(charge_settle, duration)};{key(timing.loaded, duration)};1" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
                "    </circle>",
                f'    <circle id="ammo-{index}" r="{fmt(AMMO_RADIUS)}" fill="{AMMO_COLOR}" stroke="#006d32" stroke-width="1" opacity="0">',
                f'      <title>{escape(day.date)}: {day.count} contributions launched from the muzzle as pea {index}</title>',
                f'      <animate attributeName="cx" values="{PLANT_X};{PLANT_X};{fmt(timing.impact_x)};{fmt(timing.impact_x)};{PLANT_X}" '
                f'keyTimes="0;{key(timing.loaded, duration)};{key(timing.impact, duration)};{key(duration - 0.02, duration)};1" calcMode="linear" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
                f'      <animate attributeName="cy" values="{PLANT_Y};{PLANT_Y};{fmt(timing.impact_y)};{fmt(timing.impact_y)};{PLANT_Y}" '
                f'keyTimes="0;{key(timing.loaded, duration)};{key(timing.impact, duration)};{key(duration - 0.02, duration)};1" calcMode="linear" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
                '      <animate attributeName="opacity" values="0;0;1;1;0;0" '
                f'keyTimes="0;{key(timing.loaded - 0.01, duration)};{key(timing.loaded, duration)};{key(timing.impact - 0.01, duration)};{key(timing.impact, duration)};1" calcMode="discrete" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
                "    </circle>",
            ]
        )
    peas.append("  </g>")
    return "\n".join(peas)


def frame_animation(
    frame_positions: tuple[int, ...],
    frame_seconds: float,
    stop_time: float,
    duration: float,
    hold_position: int,
) -> str:
    times = [0.0]
    positions = [frame_positions[0]]
    frame_index = 1
    current = frame_seconds
    while current < stop_time - 0.001:
        times.append(current)
        positions.append(frame_positions[frame_index % len(frame_positions)])
        current += frame_seconds
        frame_index += 1
    if stop_time > times[-1] + 0.001:
        times.append(stop_time)
        positions.append(hold_position)
    else:
        positions[-1] = hold_position
    times.append(duration)
    positions.append(frame_positions[0])
    return (
        f'<animate attributeName="x" values="{";".join(str(value) for value in positions)}" '
        f'keyTimes="{";".join(key(value, duration) for value in times)}" calcMode="discrete" '
        f'dur="{fmt(duration)}s" repeatCount="indefinite"/>'
    )


def plant_frame_animation(timings: list[Timing], duration: float) -> str:
    """Pose-to-pose firing: anticipate, compress, flash, recoil, settle."""
    frame_positions = (4, -226, -456, -686, -916, -1146)
    events: list[tuple[float, int]] = [(0.0, frame_positions[0])]
    for timing in timings:
        events.extend(
            [
                (timing.take, frame_positions[5]),
                (timing.take + 0.10, frame_positions[1]),
                (timing.loaded - 0.08, frame_positions[1]),
                (timing.loaded, frame_positions[4]),
                (timing.loaded + 0.08, frame_positions[5]),
                (timing.loaded + 0.18, frame_positions[0]),
            ]
        )
    events.sort(key=lambda event: event[0])
    events.append((duration, frame_positions[0]))
    return (
        f'<animate attributeName="x" values="{";".join(str(position) for _, position in events)}" '
        f'keyTimes="{";".join(key(moment, duration) for moment, _ in events)}" calcMode="discrete" '
        f'dur="{fmt(duration)}s" repeatCount="indefinite"/>'
    )


def zombie_frame_animation(battle_end: float, duration: float) -> str:
    # Walking ends when the zombie reaches its attack position; the bite pose is
    # then supplied by the ImageGen attack frames.
    return frame_animation((1030, 790, 550, 310, 70, -170), 0.2, battle_end, duration, 1030)


def original_sprite_visibility(hide_at: float, outcome_end: float, duration: float) -> str:
    return (
        '      <animate attributeName="visibility" values="visible;visible;hidden;hidden;visible" '
        f'keyTimes="0;{key(hide_at, duration)};{key(hide_at + 0.01, duration)};{key(outcome_end, duration)};1" '
        f'calcMode="discrete" dur="{fmt(duration)}s" repeatCount="indefinite"/>'
    )


def scheduled_frame_images(
    prefix: str,
    frames: list[Path],
    events: list[tuple[float, int | None]],
    x: float,
    y: float,
    width: float,
    height: float,
    duration: float,
    indent: str,
    frame_y_offsets: tuple[float, ...] | None = None,
) -> str:
    """Switch pre-cropped ImageGen frames with browser-stable discrete timing."""
    key_times = ";".join(key(time_value, duration) for time_value, _frame in events)
    images: list[str] = []
    for frame_index, frame_path in enumerate(frames):
        frame_y = y + (frame_y_offsets[frame_index] if frame_y_offsets else 0.0)
        values = ";".join(
            "inline" if active_frame == frame_index else "none"
            for _time, active_frame in events
        )
        images.extend(
            [
                f'{indent}<image id="{prefix}-{frame_index}" x="{fmt(x)}" y="{fmt(frame_y)}" width="{fmt(width)}" height="{fmt(height)}" preserveAspectRatio="none" href="{image_data_uri(frame_path)}" display="none">',
                f'{indent}  <animate attributeName="display" values="{values}" keyTimes="{key_times}" calcMode="discrete" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
                f"{indent}</image>",
            ]
        )
    return "\n".join(images)


def cycling_events(
    start: float | None,
    end: float,
    frame_count: int,
    duration: float,
    frame_seconds: float,
) -> list[tuple[float, int | None]]:
    events: list[tuple[float, int | None]] = [(0.0, None)]
    if start is not None and start < end - 0.001:
        current = start
        frame_index = 0
        while current < end - 0.001:
            events.append((current, frame_index % frame_count))
            current += frame_seconds
            frame_index += 1
        events.append((end, None))
    events.append((duration, None))
    return events


def append_frame_event(
    events: list[tuple[float, int | None]], moment: float, frame: int | None
) -> None:
    """Append a strictly ordered discrete-frame event, replacing same-time events."""
    if events and abs(events[-1][0] - moment) < 0.0005:
        events[-1] = (moment, frame)
    elif not events or moment > events[-1][0]:
        events.append((moment, frame))


def critical_brain_patch(
    prefix: str,
    x: float,
    y: float,
    visible_start: float | None,
    visible_end: float,
    duration: float,
    indent: str,
) -> str:
    """Small SVG-native pixel brain used only by the surviving critical zombie."""
    if visible_start is None or visible_start >= visible_end - 0.001:
        return ""
    fade_in = min(visible_end - 0.001, visible_start + 0.01)
    fade_out = min(duration, visible_end + 0.01)
    return "\n".join(
        [
            f'{indent}<g id="{prefix}" opacity="0" style="image-rendering:pixelated">',
            f'{indent}  <animate attributeName="opacity" values="0;0;1;1;0;0" '
            f'keyTimes="0;{key(visible_start, duration)};{key(fade_in, duration)};{key(visible_end, duration)};{key(fade_out, duration)};1" '
            f'calcMode="discrete" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
            f'{indent}  <path d="M{fmt(x + 3)} {fmt(y + 3)}h4v-3h11v2h5v4h3v10h-4v5h-5v3h-13v-3h-5v-5h-3v-8h4z" fill="#4b0710"/>',
            f'{indent}  <rect x="{fmt(x + 4)}" y="{fmt(y + 4)}" width="7" height="7" fill="#d45c78"/>',
            f'{indent}  <rect x="{fmt(x + 12)}" y="{fmt(y + 3)}" width="8" height="6" fill="#ed8797"/>',
            f'{indent}  <rect x="{fmt(x + 8)}" y="{fmt(y + 10)}" width="12" height="7" fill="#b83e62"/>',
            f'{indent}  <rect x="{fmt(x + 17)}" y="{fmt(y + 9)}" width="6" height="8" fill="#f0a1a9"/>',
            f'{indent}  <path d="M{fmt(x + 6)} {fmt(y + 6)}h3v4h4v-5h3v5h4v4h-3v4h-4v-4h-4v5h-3z" fill="#76203b"/>',
            f'{indent}  <rect x="{fmt(x + 21)}" y="{fmt(y + 18)}" width="3" height="7" fill="#8e111d">',
            f'{indent}    <animate attributeName="height" values="3;7;4;7;3" dur="0.72s" repeatCount="indefinite"/>',
            f'{indent}  </rect>',
            f'{indent}</g>',
        ]
    )


def headless_success_events(
    phases: CombatPhases,
    timings: list[Timing],
    outcome_end: float,
    duration: float,
) -> list[tuple[float, int | None]]:
    events: list[tuple[float, int | None]] = [(0.0, None)]
    if phases.head_loss is None or phases.lethal is None:
        events.append((duration, None))
        return events

    head_loss = phases.head_loss
    lethal = phases.lethal
    post_hits = [timing.impact for timing in timings if timing.impact > head_loss + 0.001]
    append_frame_event(events, head_loss, 2)
    first_post = post_hits[0] if post_hits else lethal
    append_frame_event(events, min(head_loss + 0.14, first_post - 0.02), 0)

    nonlethal_hits = [moment for moment in post_hits if moment < lethal - 0.001]
    for index, moment in enumerate(nonlethal_hits):
        next_moment = (
            nonlethal_hits[index + 1]
            if index + 1 < len(nonlethal_hits)
            else lethal
        )
        append_frame_event(events, moment, 2 if index % 2 == 0 else 3)
        recover = min(moment + 0.14, next_moment - 0.02)
        append_frame_event(events, recover, index % 2)

    append_frame_event(events, lethal, 4)
    append_frame_event(events, lethal + 0.16, 5)
    append_frame_event(events, lethal + 0.40, 6)
    append_frame_event(events, lethal + 0.68, 7)
    append_frame_event(events, outcome_end, None)
    append_frame_event(events, duration, None)
    return events


def zombie_generated_combat(
    damaged_walk_frames: list[Path],
    critical_walk_frames: list[Path],
    headless_frames: list[Path],
    phases: CombatPhases,
    timings: list[Timing],
    success: bool,
    battle_end: float,
    failure_attack_start: float,
    outcome_end: float,
    duration: float,
) -> str:
    """Render body damage while detached parts remain in world coordinates."""
    motion_end = phases.lethal if success and phases.lethal is not None else battle_end
    translate = SUCCESS_TRANSLATE if success else FAILURE_TRANSLATE
    walk_end = phases.lethal if success and phases.lethal is not None else failure_attack_start
    arm_loss = phases.arm_loss
    head_loss = phases.head_loss if success else None
    parts = [
        '  <g id="zombie-generated-combat" filter="url(#shadow)" style="image-rendering:pixelated">',
        '    <animateTransform attributeName="transform" type="translate" '
        f'values="0 0;{fmt(translate)} 0;{fmt(translate)} 0;0 0" '
        f'keyTimes="0;{key(motion_end, duration)};{key(outcome_end, duration)};1" '
        f'dur="{fmt(duration)}s" repeatCount="indefinite"/>',
    ]

    walk_start = arm_loss
    if walk_start is not None and walk_start < walk_end - 0.001:
        critical_start = (
            phases.critical
            if phases.critical is not None and phases.critical > walk_start + 0.001
            else None
        )
        damaged_end_candidates = [walk_end]
        if critical_start is not None:
            damaged_end_candidates.append(critical_start)
        if head_loss is not None:
            damaged_end_candidates.append(head_loss)
        damaged_end = min(damaged_end_candidates)
        if walk_start < damaged_end - 0.001:
            parts.extend(
                [
                    '    <!-- The severed arm is now a world-space prop; the one-armed body keeps advancing. -->',
                    scheduled_frame_images(
                        "zombie-damaged-walk",
                        damaged_walk_frames,
                        cycling_events(walk_start, damaged_end, len(damaged_walk_frames), duration, 0.24),
                        DAMAGED_WALK_ZOMBIE_X,
                        GENERATED_ZOMBIE_Y,
                        GENERATED_ZOMBIE_WIDTH,
                        GENERATED_ZOMBIE_HEIGHT,
                        duration,
                        "    ",
                    ),
                ]
            )

        critical_end = min(walk_end, head_loss) if head_loss is not None else walk_end
        if critical_start is not None and critical_start < critical_end - 0.001:
            parts.extend(
                [
                    '    <!-- Critical body staggers before success decapitation or a failure-state bite. -->',
                    scheduled_frame_images(
                        "zombie-critical-walk",
                        critical_walk_frames,
                        cycling_events(critical_start, critical_end, len(critical_walk_frames), duration, 0.30),
                        CRITICAL_WALK_ZOMBIE_X,
                        GENERATED_ZOMBIE_Y,
                        GENERATED_ZOMBIE_WIDTH,
                        GENERATED_ZOMBIE_HEIGHT,
                        duration,
                        "    ",
                    ),
                ]
            )
            if not success:
                parts.append(
                    critical_brain_patch(
                        "zombie-critical-walk-exposed-brain",
                        CRITICAL_WALK_ZOMBIE_X + GENERATED_ZOMBIE_WIDTH * 0.40,
                        GENERATED_ZOMBIE_Y + GENERATED_ZOMBIE_HEIGHT * 0.15,
                        critical_start,
                        critical_end,
                        duration,
                        "    ",
                    )
                )

    if success and head_loss is not None and phases.lethal is not None:
        parts.extend(
            [
                '    <!-- The head drops before the last three impacts; the headless body visibly absorbs them. -->',
                scheduled_frame_images(
                    "zombie-headless-success",
                    headless_frames,
                    headless_success_events(phases, timings, outcome_end, duration),
                    HEADLESS_ZOMBIE_X,
                    GENERATED_ZOMBIE_Y,
                    GENERATED_ZOMBIE_WIDTH,
                    GENERATED_ZOMBIE_HEIGHT,
                    duration,
                    "    ",
                ),
            ]
        )

    parts.append("  </g>")
    return "\n".join(part for part in parts if part)


def detached_parts_markup(
    arm_air_path: Path,
    arm_ground_path: Path,
    head_air_path: Path,
    head_ground_path: Path,
    phases: CombatPhases,
    success: bool,
    battle_end: float,
    outcome_end: float,
    duration: float,
) -> str:
    """Animate severed parts in world space so they never follow the body again."""
    motion_end = phases.lethal if success and phases.lethal is not None else battle_end
    translate = SUCCESS_TRANSLATE if success else FAILURE_TRANSLATE

    def body_center(moment: float) -> float:
        progress = min(1.0, max(0.0, moment / max(0.001, motion_end)))
        return ZOMBIE_REFERENCE_CENTER_X + translate * progress

    parts = ['  <g id="detached-zombie-parts" style="image-rendering:pixelated">']
    if phases.arm_loss is not None:
        start = phases.arm_loss
        land = min(outcome_end - 0.02, start + 0.58)
        origin_x = body_center(start) - 56
        origin_y = 68.0
        land_x = origin_x + 58
        land_y = 170.0
        flight_times = [0.0, start, start + 0.12, start + 0.32, land, duration]
        parts.extend(
            [
                '    <g id="detached-arm-flight" opacity="0">',
                '      <animate attributeName="opacity" values="0;0;1;1;0;0" '
                f'keyTimes="0;{key(start, duration)};{key(start + 0.01, duration)};{key(land - 0.01, duration)};{key(land, duration)};1" calcMode="discrete" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
                f'      <g transform="translate({fmt(origin_x)} {fmt(origin_y)})">',
                '        <g>',
                '          <animateTransform attributeName="transform" type="translate" values="0 0;0 0;14 -22;39 2;58 95;0 0" '
                f'keyTimes="{";".join(key(moment, duration) for moment in flight_times)}" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
                '          <g>',
                '            <animateTransform attributeName="transform" type="rotate" values="0 60 45;0 60 45;78 60 45;205 60 45;322 60 45;0 60 45" '
                f'keyTimes="{";".join(key(moment, duration) for moment in flight_times)}" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
                f'            <image x="0" y="0" width="120" height="90" preserveAspectRatio="none" href="{image_data_uri(arm_air_path)}"/>',
                '          </g>',
                '        </g>',
                '      </g>',
                '    </g>',
                f'    <image id="detached-arm-ground" x="{fmt(land_x)}" y="{fmt(land_y)}" width="120" height="90" preserveAspectRatio="none" href="{image_data_uri(arm_ground_path)}" opacity="0">',
                '      <animate attributeName="opacity" values="0;0;1;1;0" '
                f'keyTimes="0;{key(land, duration)};{key(land + 0.01, duration)};{key(outcome_end, duration)};1" calcMode="discrete" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
                '    </image>',
            ]
        )

    if success and phases.head_loss is not None:
        start = phases.head_loss
        land = min(outcome_end - 0.02, start + 0.68)
        origin_x = body_center(start) - 62
        origin_y = 22.0
        land_x = origin_x + 75
        land_y = 166.0
        flight_times = [0.0, start, start + 0.15, start + 0.38, land, duration]
        parts.extend(
            [
                '    <g id="detached-head-flight" opacity="0">',
                '      <animate attributeName="opacity" values="0;0;1;1;0;0" '
                f'keyTimes="0;{key(start, duration)};{key(start + 0.01, duration)};{key(land - 0.01, duration)};{key(land, duration)};1" calcMode="discrete" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
                f'      <g transform="translate({fmt(origin_x)} {fmt(origin_y)})">',
                '        <g>',
                '          <animateTransform attributeName="transform" type="translate" values="0 0;0 0;25 -24;62 16;75 136;0 0" '
                f'keyTimes="{";".join(key(moment, duration) for moment in flight_times)}" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
                '          <g>',
                '            <animateTransform attributeName="transform" type="rotate" values="0 60 45;0 60 45;96 60 45;238 60 45;372 60 45;0 60 45" '
                f'keyTimes="{";".join(key(moment, duration) for moment in flight_times)}" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
                f'            <image x="0" y="0" width="120" height="90" preserveAspectRatio="none" href="{image_data_uri(head_air_path)}"/>',
                '          </g>',
                '        </g>',
                '      </g>',
                '    </g>',
                f'    <image id="detached-head-ground" x="{fmt(land_x)}" y="{fmt(land_y)}" width="120" height="90" preserveAspectRatio="none" href="{image_data_uri(head_ground_path)}" opacity="0">',
                '      <animate attributeName="opacity" values="0;0;1;1;0" '
                f'keyTimes="0;{key(land, duration)};{key(land + 0.01, duration)};{key(outcome_end, duration)};1" calcMode="discrete" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
                f'      <animate attributeName="y" values="{fmt(land_y)};{fmt(land_y)};{fmt(land_y - 6)};{fmt(land_y)};{fmt(land_y)};{fmt(land_y)}" '
                f'keyTimes="0;{key(land, duration)};{key(land + 0.07, duration)};{key(land + 0.16, duration)};{key(outcome_end, duration)};1" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
                '    </image>',
            ]
        )

    parts.append("  </g>")
    return "\n".join(parts)


def plant_imagegen_sprites(
    cry_frames: list[Path],
    damage_frames: list[Path],
    ammo_out: float,
    battle_end: float,
    outcome_end: float,
    duration: float,
) -> str:
    damage_times = [battle_end + phase[2] for phase in BITE_PHASES]
    blackout = battle_end + BLACKOUT_OFFSET
    cry_start = ammo_out + 0.01
    cry_events = [
        (0.0, None),
        (cry_start, 0),
        (cry_start + 0.28, 1),
        (cry_start + 0.52, 2),
        (damage_times[0], None),
        (duration, None),
    ]
    damage_events = [
        (0.0, None),
        (damage_times[0], 1),
        (damage_times[1], 2),
        (damage_times[2], 3),
        (damage_times[2] + 0.13, 4),
        (blackout - 0.18, 5),
        (blackout, None),
        (duration, None),
    ]
    return "\n".join(
        [
            '    <!-- ImageGen: six-frame out-of-ammo and crying sequence. -->',
            scheduled_frame_images("plant-cry-imagegen", cry_frames, cry_events, 4, 30, 230, 230, duration, "    "),
            '    <!-- ImageGen: each bite switches to a genuinely damaged plant frame. -->',
            scheduled_frame_images("plant-damage-imagegen", damage_frames, damage_events, 4, 30, 230, 230, duration, "    "),
        ]
    )


def plant_group_open(
    success: bool,
    ammo_out: float,
    battle_end: float,
    outcome_end: float,
    duration: float,
) -> str:
    lines = [
        '  <g id="plant-sprite" clip-path="url(#plant-window)" style="image-rendering:pixelated">'
    ]
    if not success:
        cry_settle = min(battle_end + BITE_PHASES[0][0] - 0.08, ammo_out + 0.32)
        phase_times: list[float] = [0.0, ammo_out, cry_settle]
        transforms = ["0 0", "0 0", "-2 5"]
        for anticipation, snap, _damage, recovery in BITE_PHASES:
            phase_times.extend(
                [
                    battle_end + anticipation,
                    battle_end + snap,
                    battle_end + recovery,
                ]
            )
            transforms.extend(["-2 5", "-12 4", "-2 7"])
        blackout = battle_end + BLACKOUT_OFFSET
        phase_times.extend([blackout, outcome_end, duration])
        transforms.extend(["-2 10", "-2 10", "0 0"])
        lines.extend(
            [
                '    <animateTransform attributeName="transform" type="translate" '
                f'values="{";".join(transforms)}" keyTimes="{";".join(key(value, duration) for value in phase_times)}" '
                f'dur="{fmt(duration)}s" repeatCount="indefinite"/>',
                '    <animate attributeName="opacity" values="1;1;0;0;1" '
                f'keyTimes="0;{key(blackout, duration)};{key(blackout + 0.08, duration)};{key(outcome_end, duration)};1" '
                f'calcMode="discrete" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
            ]
        )
    else:
        lines.extend(
            [
                '    <animateTransform attributeName="transform" type="translate" '
                'values="0 0;0 0;-7 1;2 -5;-2 0;0 -3;0 -3;0 0" '
                f'keyTimes="0;{key(battle_end, duration)};{key(battle_end + 0.12, duration)};{key(battle_end + 0.30, duration)};{key(battle_end + 0.48, duration)};{key(battle_end + 0.70, duration)};{key(outcome_end, duration)};1" '
                f'dur="{fmt(duration)}s" repeatCount="indefinite"/>',
            ]
        )
    return "\n".join(lines)


def plant_emotion_markup(
    success: bool,
    ammo_out: float,
    battle_end: float,
    outcome_end: float,
    duration: float,
) -> str:
    if success:
        return "  <!-- The successful plant recoils from the final shot, then celebrates the zombie defeat. -->"
    return "  <!-- ImageGen crying frames communicate that the plant has run out of contribution dots. -->"


def zombie_animation(success: bool, battle_end: float, outcome_end: float, duration: float) -> str:
    if success:
        return (
            '    <animateTransform attributeName="transform" type="translate" '
            f'values="0 0;{fmt(SUCCESS_TRANSLATE)} 0;{fmt(SUCCESS_TRANSLATE)} 0;0 0" '
            f'keyTimes="0;{key(battle_end, duration)};{key(outcome_end, duration)};1" '
            f'dur="{fmt(duration)}s" repeatCount="indefinite"/>'
        )

    blackout = battle_end + BLACKOUT_OFFSET
    return (
        '    <animateTransform attributeName="transform" type="translate" '
        f'values="0 0;{fmt(FAILURE_TRANSLATE)} 0;{fmt(FAILURE_TRANSLATE)} 0;{fmt(FAILURE_TRANSLATE)} 0;0 0" '
        f'keyTimes="0;{key(battle_end, duration)};{key(blackout, duration)};{key(outcome_end, duration)};1" '
        f'dur="{fmt(duration)}s" repeatCount="indefinite"/>'
    )


def zombie_imagegen_attack(
    attack_frames: list[Path],
    frame_order: tuple[int, int, int, int, int, int],
    phase_label: str,
    battle_end: float,
    visible_start: float,
    outcome_end: float,
    duration: float,
) -> str:
    blackout = battle_end + BLACKOUT_OFFSET
    events: list[tuple[float, int | None]] = [
        (0.0, None),
        (visible_start, frame_order[0]),
    ]
    for anticipation, snap, damage, recovery in BITE_PHASES:
        pre = battle_end + anticipation
        events.extend(
            [
                (pre, frame_order[0]),
                (pre + 0.06, frame_order[1]),
                (battle_end + snap, frame_order[2]),
                (battle_end + damage, frame_order[3]),
                (battle_end + recovery - 0.05, frame_order[4]),
                (battle_end + recovery, frame_order[5]),
            ]
        )
    events.extend([(blackout, None), (duration, None)])
    lunge_events: list[tuple[float, float]] = [(0.0, 0.0), (visible_start, 0.0)]
    for anticipation, snap, damage, recovery in BITE_PHASES:
        pre = battle_end + anticipation
        lunge_events.extend(
            [
                (pre, 0.0),
                (pre + 0.06, 0.0),
                (battle_end + snap, -24.0),
                (battle_end + damage, -38.0),
                (battle_end + recovery - 0.05, -12.0),
                (battle_end + recovery, 0.0),
            ]
        )
    lunge_events.extend([(blackout, 0.0), (duration, 0.0)])
    lunge_values = ";".join(f"{fmt(offset)} 0" for _, offset in lunge_events)
    lunge_times = ";".join(key(moment, duration) for moment, _ in lunge_events)
    attack_x = {
        "intact": INTACT_BITE_ZOMBIE_X,
        "damaged": DAMAGED_BITE_ZOMBIE_X,
        "critical": CRITICAL_BITE_ZOMBIE_X,
    }[phase_label]
    layers = [
        f'  <!-- ImageGen {phase_label} bite: anticipation, open jaw, lunge, chew, pull, recovery. -->',
        f'  <g id="zombie-{phase_label}-bite-lunge">',
        '    <animateTransform attributeName="transform" type="translate" '
        f'values="{lunge_values}" keyTimes="{lunge_times}" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
        scheduled_frame_images(
            f"zombie-{phase_label}-bite",
            attack_frames,
            events,
            attack_x + FAILURE_TRANSLATE,
            GENERATED_ZOMBIE_Y,
            GENERATED_ZOMBIE_WIDTH,
            GENERATED_ZOMBIE_HEIGHT,
            duration,
            "    ",
        ),
    ]
    if phase_label == "critical":
        layers.append(
            critical_brain_patch(
                "zombie-critical-bite-exposed-brain",
                attack_x + FAILURE_TRANSLATE + GENERATED_ZOMBIE_WIDTH * 0.40,
                GENERATED_ZOMBIE_Y + GENERATED_ZOMBIE_HEIGHT * 0.15,
                visible_start,
                blackout,
                duration,
                "    ",
            )
        )
    layers.append("  </g>")
    return "\n".join(layer for layer in layers if layer)


def zombie_shadow(
    success: bool,
    battle_end: float,
    death_time: float | None,
    outcome_end: float,
    duration: float,
) -> str:
    if success:
        collapse_start = death_time if death_time is not None else battle_end
        end_x = 1150 + SUCCESS_TRANSLATE
        return "\n".join(
            [
                '<ellipse cy="247" rx="80" ry="12" fill="#020a09" opacity=".55">',
                f'  <animate attributeName="cx" values="1150;{fmt(end_x)};{fmt(end_x)};{fmt(end_x)};1150" keyTimes="0;{key(collapse_start, duration)};{key(collapse_start + 2.02, duration)};{key(outcome_end, duration)};1" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
                f'  <animate attributeName="rx" values="80;80;70;52;29;12;0;0;80" keyTimes="0;{key(collapse_start, duration)};{key(collapse_start + 0.42, duration)};{key(collapse_start + 0.72, duration)};{key(collapse_start + 1.04, duration)};{key(collapse_start + 1.36, duration)};{key(collapse_start + 2.02, duration)};{key(outcome_end, duration)};1" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
                f'  <animate attributeName="opacity" values=".55;.55;.48;.34;.20;.12;0;0;.55" keyTimes="0;{key(collapse_start, duration)};{key(collapse_start + 0.42, duration)};{key(collapse_start + 0.72, duration)};{key(collapse_start + 1.04, duration)};{key(collapse_start + 1.36, duration)};{key(collapse_start + 2.02, duration)};{key(outcome_end, duration)};1" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
                "</ellipse>",
            ]
        )
    end_translate = SUCCESS_TRANSLATE if success else FAILURE_TRANSLATE
    end_x = 1150 + end_translate
    values = f"1150;{fmt(end_x)};{fmt(end_x)};1150"
    return (
        '<ellipse cy="247" rx="80" ry="12" fill="#020a09" opacity=".55">'
        f'<animate attributeName="cx" values="{values}" keyTimes="0;{key(battle_end, duration)};{key(outcome_end, duration)};1" '
        f'dur="{fmt(duration)}s" repeatCount="indefinite"/>'
        '</ellipse>'
    )


def bite_action_markup(success: bool, battle_end: float, outcome_end: float, duration: float) -> str:
    return (
        "  <!-- Bite poses and plant damage are rendered entirely from ImageGen sprite frames. -->"
        if not success
        else "  <!-- The target was reached: the final pea triggers the ImageGen zombie death sequence. -->"
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


BRAIN_PIXELS = (
    "00011100111000",
    "01122211222110",
    "12222211222221",
    "12232211223221",
    "12222111122221",
    "12222111122221",
    "12232211223221",
    "01122211222110",
    "00112211221100",
    "00011100111000",
)


def brain_icon_markup(
    success: bool,
    reveal: float,
    outcome_end: float,
    duration: float,
) -> str:
    cell = 5
    width = len(BRAIN_PIXELS[0]) * cell
    start_x = 640 - width / 2
    start_y = 22
    palette = (
        ("#0e4429", "#39d353", "#b7ff72", "#f0fff4")
        if success
        else ("#6e0f14", "#f85149", "#ff7b72", "#fff0ee")
    )
    pixels: list[str] = [
        f'  <g id="{"saved" if success else "eaten"}-brain-icon" opacity="0" style="image-rendering:pixelated">',
        f'    <title>{"Brain saved" if success else "Brain eaten"} 🧠</title>',
        '    <animate attributeName="opacity" values="0;0;1;1;0" '
        f'keyTimes="0;{key(reveal, duration)};{key(reveal + 0.12, duration)};{key(outcome_end, duration)};1" '
        f'dur="{fmt(duration)}s" repeatCount="indefinite"/>',
    ]
    for row_index, row in enumerate(BRAIN_PIXELS):
        for col_index, value in enumerate(row):
            if value == "0":
                continue
            color = palette[int(value)]
            pixels.append(
                f'    <rect x="{fmt(start_x + col_index * cell)}" y="{start_y + row_index * cell}" width="{cell}" height="{cell}" fill="{color}"/>'
            )
    pixels.append("  </g>")
    return "\n".join(pixels)


def success_atmosphere(battle_end: float, outcome_end: float, duration: float) -> str:
    # The skull gets a readable hold before the left-to-right victory sweep begins.
    overlay_start = battle_end + 2.02
    flash = battle_end + 2.18
    return "\n".join(
        [
            '  <g id="success-blackout">',
            '    <rect x="0" y="0" width="1280" height="300" rx="18" fill="#010603" opacity="0">',
            '      <animate attributeName="opacity" values="0;0;.98;.98;0" '
            f'keyTimes="0;{key(overlay_start, duration)};{key(overlay_start + 0.18, duration)};{key(outcome_end, duration)};1" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
            "    </rect>",
            '    <rect x="0" y="0" width="1280" height="300" rx="18" fill="#39d353" opacity="0">',
            '      <animate attributeName="opacity" values="0;0;.32;.07;0;0" '
            f'keyTimes="0;{key(flash, duration)};{key(flash + 0.035, duration)};{key(flash + 0.11, duration)};{key(flash + 0.24, duration)};1" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
            "    </rect>",
            '    <rect x="1.5" y="1.5" width="1277" height="297" rx="17" fill="none" stroke="#39d353" stroke-width="3" opacity="0">',
            '      <animate attributeName="opacity" values="0;0;.95;.38;.82;.72;0" '
            f'keyTimes="0;{key(flash, duration)};{key(flash + 0.04, duration)};{key(flash + 0.10, duration)};{key(flash + 0.18, duration)};{key(outcome_end, duration)};1" calcMode="discrete" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
            "    </rect>",
            "  </g>",
        ]
    )


def success_title_imagegen(
    image_path: Path, battle_end: float, outcome_end: float, duration: float
) -> str:
    reveal = battle_end + 2.24
    expanded = battle_end + 2.72
    settled = battle_end + 2.90
    source = image_data_uri(image_path)
    return "\n".join(
        [
            "  <!-- The lethal impact reveals LAWN CLEAR; no spent contribution dots respawn. -->",
            "  <defs>",
            f'    <image id="success-title-imagegen-source" x="80" y="0" width="1120" height="300" preserveAspectRatio="none" href="{source}"/>',
            '    <clipPath id="success-title-reveal-clip"><rect x="80" y="0" width="0" height="300">',
            f'      <animate attributeName="width" values="0;0;1120;1120;1120;0" keyTimes="0;{key(reveal, duration)};{key(expanded, duration)};{key(settled, duration)};{key(outcome_end, duration)};1" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
            "    </rect></clipPath>",
            "  </defs>",
            '  <g id="success-title-imagegen" clip-path="url(#success-title-reveal-clip)" opacity="0" style="image-rendering:pixelated">',
            '    <animate attributeName="opacity" values="0;0;1;1;0" '
            f'keyTimes="0;{key(reveal, duration)};{key(reveal + 0.02, duration)};{key(outcome_end, duration)};1" calcMode="discrete" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
            '    <animateTransform attributeName="transform" type="translate" values="-36 7;-36 7;8 -2;0 0;0 0;-36 7" '
            f'keyTimes="0;{key(reveal, duration)};{key(expanded, duration)};{key(settled, duration)};{key(outcome_end, duration)};1" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
            '    <use href="#success-title-imagegen-source"/>',
            "  </g>",
        ]
    )


def success_stats(total: int, target: int, battle_end: float, outcome_end: float, duration: float) -> str:
    reveal = battle_end + 3.14
    label = f"{total} / {target} CONTRIBUTIONS  ·  LAWN CLEAR"
    return "\n".join(
        [
            '  <g id="success-dynamic-stats" opacity="0">',
            '    <animate attributeName="opacity" values="0;0;1;1;0" '
            f'keyTimes="0;{key(reveal, duration)};{key(reveal + 0.16, duration)};{key(outcome_end, duration)};1" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
            '    <animateTransform attributeName="transform" type="translate" values="0 9;0 9;0 0;0 0;0 9" '
            f'keyTimes="0;{key(reveal, duration)};{key(reveal + 0.16, duration)};{key(outcome_end, duration)};1" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
            '    <rect x="407" y="268" width="466" height="25" rx="3" fill="#010b05" stroke="#39d353" stroke-width="1.5"/>',
            f'    <text x="640" y="285" text-anchor="middle" fill="#b7ffbf" font-family="Courier New,monospace" font-size="13" font-weight="700" letter-spacing="1.15">{label}</text>',
            "  </g>",
        ]
    )


def failure_title_imagegen(
    image_path: Path,
    battle_end: float,
    outcome_end: float,
    duration: float,
) -> str:
    """Animate one ImageGen title card as independently timed cinematic layers."""
    blackout = battle_end + BLACKOUT_OFFSET
    top_reveal = blackout + 0.06
    top_land = blackout + 0.35
    top_rebound = blackout + 0.48
    top_settle = blackout + 0.60
    bottom_reveal = blackout + 0.20
    bottom_land = blackout + 0.55
    bottom_rebound = blackout + 0.70
    bottom_settle = blackout + 0.84
    hands_start = blackout + 0.45
    hands_arrive = blackout + 0.98
    drip_start = blackout + 0.96
    drip_end = blackout + 1.78
    source = image_data_uri(image_path)

    return "\n".join(
        [
            "  <!-- ImageGen failure typography, split into animated crops without duplicating the bitmap. -->",
            "  <defs>",
            f'    <image id="failure-title-imagegen-source" x="220" y="0" width="840" height="280" preserveAspectRatio="none" href="{source}"/>',
            '    <clipPath id="failure-title-top-clip"><rect x="270" y="0" width="740" height="140"/></clipPath>',
            '    <clipPath id="failure-title-bottom-clip"><rect x="270" y="140" width="740" height="128"/></clipPath>',
            '    <clipPath id="failure-left-hand-clip"><rect x="220" y="45" width="100" height="220"/></clipPath>',
            '    <clipPath id="failure-right-hand-clip"><rect x="960" y="45" width="100" height="220"/></clipPath>',
            '    <clipPath id="failure-glitch-a-clip"><rect x="220" y="72" width="840" height="15"/></clipPath>',
            '    <clipPath id="failure-glitch-b-clip"><rect x="220" y="184" width="840" height="14"/></clipPath>',
            '    <clipPath id="failure-drip-clip"><rect x="250" y="236" width="780" height="48"/></clipPath>',
            "  </defs>",
            '  <rect id="failure-red-flash" x="0" y="0" width="1280" height="300" fill="#a9000b" opacity="0">',
            '    <animate attributeName="opacity" values="0;0;.88;.16;0;0" '
            f'keyTimes="0;{key(blackout, duration)};{key(blackout + 0.035, duration)};{key(blackout + 0.09, duration)};{key(blackout + 0.18, duration)};1" '
            f'dur="{fmt(duration)}s" repeatCount="indefinite"/>',
            "  </rect>",
            '  <g id="failure-title-imagegen" opacity="0" style="image-rendering:pixelated">',
            '    <animate attributeName="opacity" values="0;0;1;1;0" '
            f'keyTimes="0;{key(top_reveal, duration)};{key(top_reveal + 0.02, duration)};{key(outcome_end, duration)};1" '
            f'calcMode="discrete" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
            '    <g id="failure-title-impact-shake">',
            '      <animateTransform attributeName="transform" type="translate" '
            'values="0 0;0 0;-8 3;6 -2;-3 1;0 0;7 2;-5 -2;0 0;0 0;0 0" '
            f'keyTimes="0;{key(top_land, duration)};{key(top_land + 0.04, duration)};{key(top_land + 0.08, duration)};{key(top_land + 0.12, duration)};{key(bottom_land, duration)};{key(bottom_land + 0.04, duration)};{key(bottom_land + 0.08, duration)};{key(bottom_land + 0.13, duration)};{key(outcome_end, duration)};1" '
            f'calcMode="discrete" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
            '      <g clip-path="url(#failure-title-top-clip)">',
            "        <g>",
            '          <animateTransform attributeName="transform" type="translate" values="0 -150;0 -150;0 13;0 -5;0 0;0 0;0 -150" '
            f'keyTimes="0;{key(top_reveal, duration)};{key(top_land, duration)};{key(top_rebound, duration)};{key(top_settle, duration)};{key(outcome_end, duration)};1" '
            f'dur="{fmt(duration)}s" repeatCount="indefinite"/>',
            '          <g clip-path="url(#failure-title-top-clip)"><use href="#failure-title-imagegen-source"/></g>',
            "        </g>",
            "      </g>",
            '      <g clip-path="url(#failure-title-bottom-clip)">',
            "        <g>",
            '          <animateTransform attributeName="transform" type="translate" values="0 150;0 150;0 -11;0 4;0 0;0 0;0 150" '
            f'keyTimes="0;{key(bottom_reveal, duration)};{key(bottom_land, duration)};{key(bottom_rebound, duration)};{key(bottom_settle, duration)};{key(outcome_end, duration)};1" '
            f'dur="{fmt(duration)}s" repeatCount="indefinite"/>',
            '          <g clip-path="url(#failure-title-bottom-clip)"><use href="#failure-title-imagegen-source"/></g>',
            "        </g>",
            "      </g>",
            '      <g clip-path="url(#failure-left-hand-clip)">',
            "        <g>",
            '          <animateTransform attributeName="transform" type="translate" values="-125 0;-125 0;8 0;-3 0;0 0;0 0;-125 0" '
            f'keyTimes="0;{key(hands_start, duration)};{key(hands_arrive, duration)};{key(hands_arrive + 0.10, duration)};{key(hands_arrive + 0.20, duration)};{key(outcome_end, duration)};1" '
            f'dur="{fmt(duration)}s" repeatCount="indefinite"/>',
            '          <g clip-path="url(#failure-left-hand-clip)"><use href="#failure-title-imagegen-source"/></g>',
            "        </g>",
            "      </g>",
            '      <g clip-path="url(#failure-right-hand-clip)">',
            "        <g>",
            '          <animateTransform attributeName="transform" type="translate" values="125 0;125 0;-8 0;3 0;0 0;0 0;125 0" '
            f'keyTimes="0;{key(hands_start, duration)};{key(hands_arrive, duration)};{key(hands_arrive + 0.10, duration)};{key(hands_arrive + 0.20, duration)};{key(outcome_end, duration)};1" '
            f'dur="{fmt(duration)}s" repeatCount="indefinite"/>',
            '          <g clip-path="url(#failure-right-hand-clip)"><use href="#failure-title-imagegen-source"/></g>',
            "        </g>",
            "      </g>",
            "    </g>",
            '    <g id="failure-title-glitch-a" clip-path="url(#failure-glitch-a-clip)" opacity="0" style="mix-blend-mode:screen">',
            '      <animate attributeName="opacity" values="0;0;.85;0;.65;0;0" '
            f'keyTimes="0;{key(blackout + 0.29, duration)};{key(blackout + 0.33, duration)};{key(blackout + 0.39, duration)};{key(blackout + 0.47, duration)};{key(blackout + 0.54, duration)};1" '
            f'calcMode="discrete" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
            '      <animateTransform attributeName="transform" type="translate" values="0 0;0 0;14 0;-10 0;8 0;0 0;0 0" '
            f'keyTimes="0;{key(blackout + 0.29, duration)};{key(blackout + 0.33, duration)};{key(blackout + 0.39, duration)};{key(blackout + 0.47, duration)};{key(blackout + 0.54, duration)};1" '
            f'calcMode="discrete" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
            '      <use href="#failure-title-imagegen-source"/>',
            "    </g>",
            '    <g id="failure-title-glitch-b" clip-path="url(#failure-glitch-b-clip)" opacity="0" style="mix-blend-mode:screen">',
            '      <animate attributeName="opacity" values="0;0;.8;0;.6;0;0" '
            f'keyTimes="0;{key(blackout + 0.50, duration)};{key(blackout + 0.55, duration)};{key(blackout + 0.62, duration)};{key(blackout + 0.70, duration)};{key(blackout + 0.78, duration)};1" '
            f'calcMode="discrete" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
            '      <animateTransform attributeName="transform" type="translate" values="0 0;0 0;-13 0;9 0;-7 0;0 0;0 0" '
            f'keyTimes="0;{key(blackout + 0.50, duration)};{key(blackout + 0.55, duration)};{key(blackout + 0.62, duration)};{key(blackout + 0.70, duration)};{key(blackout + 0.78, duration)};1" '
            f'calcMode="discrete" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
            '      <use href="#failure-title-imagegen-source"/>',
            "    </g>",
            '    <g id="failure-title-generated-drips" clip-path="url(#failure-drip-clip)" opacity="0" style="mix-blend-mode:screen">',
            '      <animate attributeName="opacity" values="0;0;.15;.9;.9;0" '
            f'keyTimes="0;{key(drip_start, duration)};{key(drip_start + 0.10, duration)};{key(drip_start + 0.32, duration)};{key(outcome_end, duration)};1" '
            f'dur="{fmt(duration)}s" repeatCount="indefinite"/>',
            '      <animateTransform attributeName="transform" type="translate" values="0 0;0 0;0 2;0 16;0 16;0 0" '
            f'keyTimes="0;{key(drip_start, duration)};{key(drip_start + 0.10, duration)};{key(drip_end, duration)};{key(outcome_end, duration)};1" '
            f'dur="{fmt(duration)}s" repeatCount="indefinite"/>',
            '      <use href="#failure-title-imagegen-source"/>',
            "    </g>",
            "  </g>",
        ]
    )


def failure_stats(total: int, target: int, battle_end: float, outcome_end: float, duration: float) -> str:
    reveal = battle_end + BLACKOUT_OFFSET + 1.18
    label = f"{total} / {target} CONTRIBUTIONS  ·  RUN TERMINATED"
    return "\n".join(
        [
            '  <g id="failure-dynamic-stats" opacity="0">',
            '    <animate attributeName="opacity" values="0;0;1;1;0" '
            f'keyTimes="0;{key(reveal, duration)};{key(reveal + 0.16, duration)};{key(outcome_end, duration)};1" '
            f'dur="{fmt(duration)}s" repeatCount="indefinite"/>',
            '    <animateTransform attributeName="transform" type="translate" values="0 9;0 9;0 0;0 0;0 9" '
            f'keyTimes="0;{key(reveal, duration)};{key(reveal + 0.16, duration)};{key(outcome_end, duration)};1" '
            f'dur="{fmt(duration)}s" repeatCount="indefinite"/>',
            '    <rect x="407" y="268" width="466" height="25" rx="3" fill="#050001" stroke="#73131b" stroke-width="1.5"/>',
            f'    <text x="640" y="285" text-anchor="middle" fill="#ffb3ad" font-family="Courier New,monospace" font-size="13" font-weight="700" letter-spacing="1.25">{label}</text>',
            "  </g>",
        ]
    )


def failure_atmosphere(battle_end: float, outcome_end: float, duration: float) -> str:
    blackout = battle_end + BLACKOUT_OFFSET
    reveal = blackout + 0.11
    splatters = (
        (36, 34, 13),
        (69, 19, 7),
        (113, 51, 10),
        (1198, 31, 12),
        (1241, 58, 8),
        (1160, 72, 6),
        (40, 251, 9),
        (84, 276, 13),
        (1218, 244, 11),
        (1254, 272, 7),
    )
    parts = [
        '  <g id="failure-blackout">',
        '    <rect x="0" y="0" width="1280" height="300" rx="18" fill="#020203" opacity="0">',
        '      <animate attributeName="opacity" values="0;0;1;1;0" '
        f'keyTimes="0;{key(blackout, duration)};{key(blackout + 0.08, duration)};{key(outcome_end, duration)};1" '
        f'calcMode="discrete" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
        "    </rect>",
        '    <g fill="#7a1118" opacity="0">',
        '      <animate attributeName="opacity" values="0;0;.82;.82;0" '
        f'keyTimes="0;{key(reveal, duration)};{key(reveal + 0.12, duration)};{key(outcome_end, duration)};1" '
        f'dur="{fmt(duration)}s" repeatCount="indefinite"/>',
        '      <path d="M0 0h1280v7H1120l-18 11-48-11H765l-29 15-37-15H392l-25 10-42-10H0Z"/>',
        '      <path d="M0 300v-6h176l21-14 39 14h285l31-18 42 18h327l22-12 31 12h306v6Z"/>',
    ]
    for x, y, size in splatters:
        parts.extend(
            [
                f'      <rect x="{x}" y="{y}" width="{size}" height="{size}"/>',
                f'      <rect x="{x + size + 5}" y="{y + size // 2}" width="{max(3, size // 2)}" height="{max(3, size // 2)}"/>',
            ]
        )
    parts.extend(
        [
            "    </g>",
            '    <rect x="0" y="0" width="1280" height="300" rx="18" fill="none" stroke="#7a1118" stroke-width="4" opacity="0">',
            '      <animate attributeName="opacity" values="0;0;.9;.35;.9;.75;0" '
            f'keyTimes="0;{key(reveal, duration)};{key(reveal + 0.03, duration)};{key(reveal + 0.08, duration)};{key(reveal + 0.13, duration)};{key(outcome_end, duration)};1" '
            f'calcMode="discrete" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
            "    </rect>",
            "  </g>",
        ]
    )
    return "\n".join(parts)


def outcome_markup(
    total: int,
    target: int,
    success: bool,
    battle_end: float,
    outcome_end: float,
    duration: float,
    failure_title_path: Path,
    success_title_path: Path,
) -> str:
    if success:
        parts = [
            success_atmosphere(battle_end, outcome_end, duration),
            success_title_imagegen(success_title_path, battle_end, outcome_end, duration),
            success_stats(total, target, battle_end, outcome_end, duration),
        ]
    else:
        parts = [
            failure_atmosphere(battle_end, outcome_end, duration),
            failure_title_imagegen(failure_title_path, battle_end, outcome_end, duration),
            failure_stats(total, target, battle_end, outcome_end, duration),
        ]
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
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Turn contribution-day dots into a configurable zombie lawn-defense challenge."
    )
    parser.add_argument("--base-svg", required=True, type=Path)
    parser.add_argument("--out-svg", required=True, type=Path)
    parser.add_argument(
        "--sprite-dir",
        type=Path,
        default=project_root / "assets" / "sprites",
    )
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
    parser.add_argument(
        "--calendar-json",
        type=Path,
        help="Optional GraphQL response fixture for deterministic offline visual QA.",
    )
    parser.add_argument("--force-total", type=int, help="Preview-only override for the displayed total and outcome.")
    args = parser.parse_args()

    if args.window_days > 365:
        parser.error("--window-days must be between 1 and 365")
    if args.battle_seconds < 6:
        parser.error("--battle-seconds must be at least 6")
    if args.force_total is not None and args.force_total < 0:
        parser.error("--force-total cannot be negative")
    plant_cry_frames = [args.sprite_dir / f"plant-cry-imagegen-{index}.gif" for index in range(6)]
    plant_damage_frames = [args.sprite_dir / f"plant-damage-imagegen-{index}.gif" for index in range(6)]
    zombie_bite_frames = [args.sprite_dir / f"zombie-bite-imagegen-{index}.gif" for index in range(6)]
    zombie_damaged_bite_frames = [
        args.sprite_dir / f"zombie-damaged-bite-imagegen-{index}.png" for index in range(6)
    ]
    zombie_critical_bite_frames = [
        args.sprite_dir / f"zombie-critical-bite-imagegen-{index}.png" for index in range(6)
    ]
    zombie_damaged_walk_frames = [
        args.sprite_dir / f"zombie-damaged-walk-imagegen-{index}.png" for index in range(4)
    ]
    zombie_critical_walk_frames = [
        args.sprite_dir / f"zombie-critical-walk-imagegen-{index}.png" for index in range(4)
    ]
    zombie_headless_success_frames = [
        args.sprite_dir / f"zombie-headless-success-imagegen-{index}.png" for index in range(8)
    ]
    detached_arm_air_path = args.sprite_dir / "zombie-detached-arm-air.png"
    detached_arm_ground_path = args.sprite_dir / "zombie-detached-arm-ground.png"
    detached_head_air_path = args.sprite_dir / "zombie-detached-head-air.png"
    detached_head_ground_path = args.sprite_dir / "zombie-detached-head-ground.png"
    failure_title_path = args.sprite_dir / "failure-title-imagegen.png"
    success_title_path = args.sprite_dir / "success-title-lawn-clear-imagegen.png"
    for sprite_path in (
        *plant_cry_frames,
        *plant_damage_frames,
        *zombie_bite_frames,
        *zombie_damaged_bite_frames,
        *zombie_critical_bite_frames,
        *zombie_damaged_walk_frames,
        *zombie_critical_walk_frames,
        *zombie_headless_success_frames,
        detached_arm_air_path,
        detached_arm_ground_path,
        detached_head_air_path,
        detached_head_ground_path,
        failure_title_path,
        success_title_path,
    ):
        if not sprite_path.is_file():
            parser.error(f"missing ImageGen asset: {sprite_path}")

    login = args.login or gh_json("api", "user")["login"]
    today = datetime.now(timezone.utc).date()
    from_date = today - timedelta(days=args.window_days - 1)
    from_iso = f"{from_date.isoformat()}T00:00:00Z"
    to_iso = f"{today.isoformat()}T23:59:59Z"
    if args.calendar_json is not None:
        payload = json.loads(args.calendar_json.read_text(encoding="utf-8"))
    else:
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
    phases = combat_phases(
        ordered_active,
        timings,
        total,
        args.target_contributions,
        success,
        battle_end,
    )
    ammo_out = timings[-1].impact if timings else INTRO_TIME + 0.9
    board_empty_at = timings[-1].loaded if timings else INTRO_TIME + 0.9
    zombie_original_hide = min(
        moment
        for moment in (phases.arm_loss, phases.head_loss, battle_end)
        if moment is not None
    )
    failure_attack_start = (
        battle_end + 0.30
        if not success
        and phases.arm_loss is not None
        and battle_end - phases.arm_loss < 0.30
        else battle_end
    )

    source = args.base_svg.read_text(encoding="utf-8")
    source = re.sub(
        r'  <!-- Contribution grid remains vector and crisp -->.*?(?=  <path d="M0 228c)',
        calendar_markup(
            days,
            ordered_active,
            timings,
            board_empty_at,
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
        plant_group_open(success, ammo_out, battle_end, outcome_end, duration),
        1,
    )
    if not success:
        source = source.replace(
            '    <g clip-path="url(#zombie-window)" filter="url(#shadow)" style="image-rendering:pixelated">',
            '    <g clip-path="url(#zombie-window)" style="image-rendering:pixelated">',
            1,
        )
    source = re.sub(
        r'<animate attributeName="x" values="4;-226;-456;-686;-916;-1146" calcMode="discrete" dur="2s" repeatCount="indefinite"/>',
        plant_frame_animation(timings, duration)
        + (
            "\n" + original_sprite_visibility(ammo_out + 0.01, outcome_end, duration)
            if not success
            else ""
        ),
        source,
        count=1,
    )
    if not success:
        source = source.replace(
            "    </image>\n  </g>",
            "    </image>\n  </g>\n"
            + plant_imagegen_sprites(
                plant_cry_frames,
                plant_damage_frames,
                ammo_out,
                battle_end,
                outcome_end,
                duration,
            )
            + "",
            1,
        )
    source = source.replace(
        '<ellipse cx="1150" cy="247" rx="72" ry="11" fill="#020a09" opacity=".55"/>',
        plant_emotion_markup(success, ammo_out, battle_end, outcome_end, duration)
        + "\n"
        + zombie_shadow(success, battle_end, phases.lethal, outcome_end, duration),
        1,
    )
    source = re.sub(
        r'    <animateTransform attributeName="transform" type="translate" values="8 0;-12 0;8 0" keyTimes="0;.52;1" dur="6s" repeatCount="indefinite"/>',
        zombie_animation(success, battle_end, outcome_end, duration),
        source,
        count=1,
    )
    source = re.sub(
        r'<animate attributeName="x" values="1030;790;550;310;70;-170" calcMode="discrete" dur="1\.2s" repeatCount="indefinite"/>',
        zombie_frame_animation(battle_end, duration)
        + "\n"
        + original_sprite_visibility(zombie_original_hide, outcome_end, duration),
        source,
        count=1,
    )
    combat_layers = zombie_generated_combat(
        zombie_damaged_walk_frames,
        zombie_critical_walk_frames,
        zombie_headless_success_frames,
        phases,
        timings,
        success,
        battle_end,
        failure_attack_start,
        outcome_end,
        duration,
    )
    combat_layers += "\n" + detached_parts_markup(
        detached_arm_air_path,
        detached_arm_ground_path,
        detached_head_air_path,
        detached_head_ground_path,
        phases,
        success,
        battle_end,
        outcome_end,
        duration,
    )
    if not success:
        if phases.failure_state == "critical":
            attack_frames = zombie_critical_bite_frames
            attack_order = (0, 1, 2, 2, 4, 5)
        elif phases.failure_state == "damaged":
            attack_frames = zombie_damaged_bite_frames
            attack_order = (0, 1, 2, 2, 4, 5)
        else:
            attack_frames = zombie_bite_frames
            attack_order = (0, 1, 2, 3, 4, 5)
        combat_layers += "\n" + zombie_imagegen_attack(
            attack_frames,
            attack_order,
            phases.failure_state,
            battle_end,
            failure_attack_start,
            outcome_end,
            duration,
        )
    source = source.replace(
        "      </image>\n    </g>\n  </g>",
        "      </image>\n    </g>\n  </g>\n" + combat_layers,
        1,
    )
    source = source.replace(
        "  <!-- Health and hits stay deterministic -->",
        bite_action_markup(success, battle_end, outcome_end, duration)
        + "\n\n  <!-- Health and hits stay deterministic -->",
        1,
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
            total,
            args.target_contributions,
            success,
            battle_end,
            outcome_end,
            duration,
            failure_title_path,
            success_title_path,
        )
        + "\n\n",
        source,
        flags=re.DOTALL,
    )
    source = re.sub(
        r'<title id="title">.*?</title>',
        f'<title id="title">Contribution lawn defense: {total} of {args.target_contributions}</title>',
        source,
    )
    source = re.sub(
        r'<desc id="desc">.*?</desc>',
        f'<desc id="desc">@{escape(login)} has {total} contributions in the last {args.window_days} days against a target of {args.target_contributions}. Every non-empty contribution cell pulses in place during the Peashooter anticipation, disappears at muzzle flash, and stays empty until the loop resets; the pea itself is born at the muzzle. At half damage the arm tears free and remains where it lands. {"Before the final three impacts the head is knocked off, remains on the lawn, and the headless body absorbs more hits before collapsing into LAWN CLEAR" if success else f"The surviving {phases.failure_state} zombie keeps its head for the three-bite failure sequence; critical failures expose a bloody half-brain"}. Only contribution dates and counts are used.</desc>',
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
                "damagePhase": "lethal" if success else phases.failure_state,
                "armLossAt": phases.arm_loss,
                "criticalAt": phases.critical,
                "headLossAt": phases.head_loss,
                "lethalAt": phases.lethal,
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
