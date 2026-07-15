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
MAX_SHOT_INTERVAL = 0.55
OUTCOME_TIME = 5.0
RESET_TIME = 1.5
SUCCESS_TRANSLATE = -620.0
FAILURE_TRANSLATE = -895.0

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


def plant_frame_animation(ammo_out: float, duration: float) -> str:
    # Stop on the neutral frame once the last contribution dot has been fired.
    return frame_animation((4, -226, -456, -686, -916, -1146), 0.175, ammo_out, duration, 4)


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
    x: int,
    y: int,
    width: int,
    height: int,
    duration: float,
    indent: str,
) -> str:
    """Switch ImageGen GIF frames; binary transparency is robust in SVG image mode."""
    key_times = ";".join(key(time_value, duration) for time_value, _frame in events)
    images: list[str] = []
    for frame_index, frame_path in enumerate(frames):
        values = ";".join(
            "inline" if active_frame == frame_index else "none"
            for _time, active_frame in events
        )
        images.extend(
            [
                f'{indent}<image id="{prefix}-{frame_index}" x="{x}" y="{y}" width="{width}" height="{height}" preserveAspectRatio="none" href="{image_data_uri(frame_path)}" display="none">',
                f'{indent}  <animate attributeName="display" values="{values}" keyTimes="{key_times}" calcMode="discrete" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
                f"{indent}</image>",
            ]
        )
    return "\n".join(images)


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
        (cry_start + 0.72, 2),
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
    return "\n".join(lines)


def plant_emotion_markup(
    success: bool,
    ammo_out: float,
    battle_end: float,
    outcome_end: float,
    duration: float,
) -> str:
    if success:
        return "  <!-- The successful plant holds after spending its final contribution dot. -->"
    return "  <!-- ImageGen crying frames communicate that the plant has run out of contribution dots. -->"


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

    blackout = battle_end + BLACKOUT_OFFSET
    return (
        '    <animateTransform attributeName="transform" type="translate" '
        f'values="0 0;{fmt(FAILURE_TRANSLATE)} 0;{fmt(FAILURE_TRANSLATE)} 0;{fmt(FAILURE_TRANSLATE)} 0;0 0" '
        f'keyTimes="0;{key(battle_end, duration)};{key(blackout, duration)};{key(outcome_end, duration)};1" '
        f'dur="{fmt(duration)}s" repeatCount="indefinite"/>'
    )


def zombie_imagegen_attack(
    attack_frames: list[Path],
    battle_end: float,
    outcome_end: float,
    duration: float,
) -> str:
    blackout = battle_end + BLACKOUT_OFFSET
    events: list[tuple[float, int | None]] = [(0.0, None), (battle_end, 0)]
    for anticipation, snap, damage, recovery in BITE_PHASES:
        pre = battle_end + anticipation
        events.extend(
            [
                (pre, 0),
                (pre + 0.06, 1),
                (battle_end + snap, 2),
                (battle_end + damage, 3),
                (battle_end + recovery - 0.05, 4),
                (battle_end + recovery, 5),
            ]
        )
    events.extend([(blackout, None), (duration, None)])
    return "\n".join(
        [
            '  <!-- ImageGen: anticipation, open jaw, lunge, chew, pull, recovery. -->',
            scheduled_frame_images(
                "zombie-imagegen-bite",
                attack_frames,
                events,
                int(ZOMBIE_X + FAILURE_TRANSLATE),
                27,
                240,
                230,
                duration,
                "  ",
            ),
        ]
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


def bite_action_markup(success: bool, battle_end: float, outcome_end: float, duration: float) -> str:
    return (
        "  <!-- Bite poses and plant damage are rendered entirely from ImageGen sprite frames. -->"
        if not success
        else "  <!-- No bite sequence: the target was reached in time. -->"
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
    ordered_active: list[Day],
    total: int,
    target: int,
    success: bool,
    battle_end: float,
    outcome_end: float,
    duration: float,
    failure_title_path: Path,
) -> str:
    if success:
        overlay_start = battle_end + 0.40
        parts = [
            '  <rect x="0" y="0" width="1280" height="300" rx="18" fill="#020604" opacity="0">',
            '    <animate attributeName="opacity" values="0;0;.98;.98;0" '
            f'keyTimes="0;{key(overlay_start, duration)};{key(overlay_start + 0.18, duration)};{key(outcome_end, duration)};1" dur="{fmt(duration)}s" repeatCount="indefinite"/>',
            "  </rect>",
            brain_icon_markup(True, overlay_start + 0.16, outcome_end, duration),
            '  <g id="victory-pixel-message">',
            victory_message(ordered_active, total, target, battle_end, outcome_end, duration),
            "  </g>",
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
        description="Turn contribution-day dots into a configurable zombie brain-defense challenge."
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
    failure_title_path = args.sprite_dir / "failure-title-imagegen.png"
    for sprite_path in (
        *plant_cry_frames,
        *plant_damage_frames,
        *zombie_bite_frames,
        failure_title_path,
    ):
        if not sprite_path.is_file():
            parser.error(f"missing ImageGen asset: {sprite_path}")

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
    ammo_out = timings[-1].impact if timings else INTRO_TIME + 0.9

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
        plant_frame_animation(ammo_out, duration)
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
        + zombie_shadow(success, battle_end, outcome_end, duration),
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
        + (
            "\n" + original_sprite_visibility(battle_end, outcome_end, duration)
            if not success
            else ""
        ),
        source,
        count=1,
    )
    if not success:
        source = source.replace(
            "      </image>\n    </g>\n  </g>",
            "      </image>\n    </g>\n  </g>\n"
            + zombie_imagegen_attack(
                zombie_bite_frames,
                battle_end,
                outcome_end,
                duration,
            ),
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
            ordered_active,
            total,
            args.target_contributions,
            success,
            battle_end,
            outcome_end,
            duration,
            failure_title_path,
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
        f'<desc id="desc">@{escape(login)} has {total} contributions in the last {args.window_days} days against a target of {args.target_contributions}. The plant stops after its final contribution dot. The zombie {"is defeated and the brain is saved" if success else "performs a three-bite ImageGen sprite sequence that progressively eats the plant before an animated ImageGen horror title card"}. Only contribution dates and counts are used.</desc>',
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
