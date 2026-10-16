"""Live view of a pipeline log: `green watch run.log` shows each download's progress and problems.

It only reads the log, so it can be started, stopped and restarted while a run goes on.
"""

import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# Seconds between redraws.
REFRESH = 1.0
# Problems listed at the bottom of the screen.
PROBLEMS = 6

LINE = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\] (\w+) - (.*)$")
FETCH = re.compile(r"^Fetching (.+?): \d+ bands over (\d+) chunks$")
PROGRESS = re.compile(r"^(.+?): (\d+)/(\d+) \(\d+%\), \S+ elapsed(?:, ~(\S+) left)?$")
SAVED = re.compile(r"^Using saved (\S+)$")
YEAR = re.compile(r"^Extracting (\d+) \(year (\d+) of (\d+)\)$")
STEP_START = re.compile(r"^▶ (.+)$")
STEP_END = re.compile(r"^✔ (.+?) in (\S+)$")
# The Earth Engine client's own retry message, shortened to its cause.
CLIENT_RETRY = re.compile(r"^Sleeping [\d.]+ seconds before retry .*?, after (.*)$")
EXCEPTION = re.compile(r"^[\w.]+(Error|Exception): ")


@dataclass
class Download:
    name: str
    total: int = 0
    done: int = 0
    started: datetime | None = None
    eta: str = ""
    saved: bool = False
    warnings: int = 0

    @property
    def finished(self) -> bool:
        return self.saved or (self.total > 0 and self.done >= self.total)


@dataclass
class Problem:
    level: str
    time: str
    message: str
    count: int = 1


@dataclass
class Run:
    command: str = ""
    steps: list[str] = field(default_factory=list)
    finished_steps: set[str] = field(default_factory=set)
    year: tuple[int, int, int] | None = None
    downloads: dict[str, Download] = field(default_factory=dict)
    problems: list[Problem] = field(default_factory=list)
    errors: int = 0
    warnings: int = 0
    failure: list[str] = field(default_factory=list)
    started: datetime | None = None
    last: datetime | None = None
    failed: bool = False

    @property
    def current(self) -> Download | None:
        live = [d for d in self.downloads.values() if not d.finished]
        return live[-1] if live else None

    @property
    def complete(self) -> bool:
        return bool(self.steps) and self.steps[0] in self.finished_steps


def _problem(run: Run, level: str, when: str, message: str) -> None:
    if level == "WARNING":
        run.warnings += 1
    else:
        run.errors += 1
    if (match := CLIENT_RETRY.match(message)) is not None:
        message = f"request retried after {match.group(1)}"
    message = re.sub(r"HTTPSConnectionPool\(host='([^']+)', port=\d+\): ", r"\1: ", message)
    last = run.problems[-1] if run.problems else None
    if last and last.level == level and last.message == message:
        last.count += 1
        last.time = when
    else:
        run.problems.append(Problem(level, when, message))
    if run.current is not None and level == "WARNING":
        run.current.warnings += 1


def parse(lines: list[str]) -> Run:
    run = Run()
    tail: list[str] = []
    for raw in lines:
        line = raw.rstrip("\n")
        if line.startswith("task: [") and not run.command:
            run.command = line.split("] ", 1)[1]
            continue
        match = LINE.match(line)
        if match is None:
            text = line.strip()
            if "Failed to run task" in text:
                run.failed = True
            elif text and "warnings.warn" not in text and "UserWarning" not in text:
                tail = [*tail, text][-8:]
            if EXCEPTION.match(text):
                run.failed = True
                _problem(run, "ERROR", "", text)
            continue
        tail = []
        stamp, level, message = match.groups()
        when = datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S")
        run.started = run.started or when
        run.last = when
        if level != "INFO":
            _problem(run, level, stamp[11:], message)
        elif m := STEP_START.match(message):
            run.steps.append(m.group(1))
        elif m := STEP_END.match(message):
            run.finished_steps.add(m.group(1))
        elif m := YEAR.match(message):
            run.year = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
        elif m := FETCH.match(message):
            run.downloads[m.group(1)] = Download(m.group(1), int(m.group(2)), started=when)
        elif m := PROGRESS.match(message):
            name, done, total, eta = m.groups()
            download = run.downloads.setdefault(name, Download(name, started=when))
            download.done, download.total, download.eta = int(done), int(total), eta or ""
        elif m := SAVED.match(message):
            run.downloads[m.group(1)] = Download(m.group(1), saved=True)
    if run.failed:
        run.failure = tail
    return run


# Colours, as 24-bit ANSI escapes.
RESET, BOLD, DIM = "\033[0m", "\033[1m", "\033[2m"


def _rgb(r: int, g: int, b: int) -> str:
    return f"\033[38;2;{r};{g};{b}m"


LEAF = _rgb(126, 214, 140)
SKY = _rgb(110, 190, 230)
SUN = _rgb(240, 196, 92)
ROSE = _rgb(240, 110, 120)
MIST = _rgb(118, 126, 140)
TRACK = _rgb(52, 58, 68)
TEXT = _rgb(226, 230, 236)

ANSI = re.compile(r"\033\[[0-9;?]*[A-Za-z]")
BLOCKS = " ▏▎▍▌▋▊▉█"


def _width(text: str) -> int:
    return len(ANSI.sub("", text))


def _clip(text: str, width: int) -> str:
    """Cut a coloured line to `width` visible characters, so it never wraps."""
    out, seen = [], 0
    for part in re.split(f"({ANSI.pattern})", text):
        if ANSI.fullmatch(part):
            out.append(part)
            continue
        room = width - seen
        if len(part) > room:
            out.append(part[: max(room - 1, 0)] + "…")
            break
        out.append(part)
        seen += len(part)
    return "".join(out) + RESET


def _bar(fraction: float, width: int, color: str) -> str:
    fraction = min(max(fraction, 0.0), 1.0)
    eighths = round(fraction * width * 8)
    full, part = divmod(eighths, 8)
    filled = "█" * full + (BLOCKS[part] if part else "")
    return f"{color}{filled}{TRACK}{'━' * (width - len(filled))}{RESET}"


def _duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m{seconds % 60:02d}s"
    return f"{seconds // 3600}h{seconds // 60 % 60:02d}m"


def _running() -> bool | None:
    try:
        found = subprocess.run(["pgrep", "-f", "green run"], capture_output=True, check=False)
    except OSError:
        return None
    return found.returncode == 0


SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def render(
    run: Run, width: int, height: int, alive: bool | None, age: float, tick: int, log: str = ""
) -> list[str]:
    now = datetime.now()
    if run.complete:
        status = f"{LEAF}{BOLD}✔ finished{RESET}"
    elif run.failed or alive is False:
        status = f"{ROSE}{BOLD}✗ stopped{RESET}"
    else:
        status = f"{SKY}{SPINNER[tick % len(SPINNER)]} running{RESET}"
    elapsed = (
        f"{MIST}{_duration((now - run.started).total_seconds())} total{RESET}"
        if run.started
        else ""
    )
    quiet = f"{SUN if age > 120 else MIST}log quiet {_duration(age)}{RESET}" if age >= 15 else ""
    lines = [
        f" {LEAF}{BOLD}🌱 green{RESET}  {status}   {elapsed}   {quiet}",
        f" {MIST}{run.command}{RESET}",
        "",
    ]

    if run.steps:
        crumbs = []
        for name in run.steps:
            color = LEAF if name in run.finished_steps else SUN
            crumbs.append(f"{color}{name}{RESET}")
        lines.append(f" {MIST}Step{RESET}   " + f" {MIST}›{RESET} ".join(crumbs))
    if run.year is not None:
        year, index, count = run.year
        done = index - 1 + (1 if run.current is None and run.downloads else 0)
        lines.append(
            f" {MIST}Year{RESET}   {TEXT}{BOLD}{year}{RESET}  {_bar(done / count, 24, SKY)}"
            f"  {TEXT}{index} of {count}{RESET}"
        )
    lines.append("")

    downloads = list(run.downloads.values())
    name_width = max([len(d.name) for d in downloads] + [12])
    bar_width = max(10, min(36, width - name_width - 42))
    room = max(height - len(lines) - PROBLEMS - 8, 3)
    saved = [d for d in downloads if d.saved]
    fetched = [d for d in downloads if not d.saved]
    if saved:
        lines.append(f" {LEAF}✓{RESET} {MIST}{len(saved)} layers already saved{RESET}")
    if len(fetched) > room:
        lines.append(f" {MIST}  … {len(fetched) - room} earlier downloads{RESET}")
    for d in fetched[-room:]:
        name = f"{d.name:<{name_width}}"
        if d.finished:
            lines.append(
                f" {LEAF}✓{RESET} {TEXT}{name}{RESET}  {_bar(1, bar_width, LEAF)}"
                f"  {LEAF}{d.total}/{d.total}{RESET}"
            )
            continue
        stuck = run.failed or alive is False
        color = ROSE if stuck else SUN if d.warnings else SKY
        mark = f"{ROSE}✗{RESET}" if stuck else f"{SKY}▸{RESET}"
        fraction = d.done / d.total if d.total else 0
        since = f"{_duration((now - d.started).total_seconds())}" if d.started else ""
        eta = f" · ~{d.eta} left" if d.eta and not stuck else ""
        retries = f"  {SUN}⚠ {d.warnings}{RESET}" if d.warnings else ""
        lines.append(
            f" {mark} {BOLD}{TEXT}{name}{RESET}  {_bar(fraction, bar_width, color)}"
            f"  {TEXT}{d.done:>3}/{d.total:<3} {100 * fraction:3.0f}%{RESET}"
            f"  {MIST}{since}{eta}{RESET}{retries}"
        )

    lines.append("")
    lines.append(
        f" {BOLD}{TEXT}Problems{RESET}   {ROSE}{run.errors} errors{RESET}"
        f"   {SUN}{run.warnings} warnings{RESET}"
    )
    if not run.problems:
        lines.append(f"   {MIST}none so far{RESET}")
    for p in run.problems[-PROBLEMS:]:
        color, mark = (SUN, "⚠") if p.level == "WARNING" else (ROSE, "✗")
        times = f" ×{p.count}" if p.count > 1 else ""
        lines.append(
            f"   {color}{mark}{RESET} {MIST}{p.time:>8}{RESET}  {color}{p.message}{times}{RESET}"
        )
    if run.failure:
        lines.append("")
        lines.append(f" {ROSE}{BOLD}Last output{RESET}")
        lines.extend(f"   {ROSE}{text}{RESET}" for text in run.failure[-4:])

    lines = lines[: height - 2]
    lines += [""] * (height - 2 - len(lines))
    lines.append(f" {DIM}{MIST}Ctrl-C to quit · watching {log}{RESET}")
    return [_clip(line, width - 1) for line in lines]


def watch(log: Path) -> None:
    out = sys.stdout
    # Draw on the alternate screen and overwrite in place, so the view never flickers or
    # scrolls; restore the terminal on exit.
    out.write("\033[?1049h\033[?25l")
    tick = 0
    try:
        while True:
            width, height = shutil.get_terminal_size((100, 32))
            try:
                lines = log.read_text(errors="replace").splitlines()
                age = time.time() - os.path.getmtime(log)
                screen = render(parse(lines), width, height, _running(), age, tick, str(log))
            except FileNotFoundError:
                screen = [f" {ROSE}No log at {log}{RESET}", f" {MIST}Waiting for it…{RESET}"]
            out.write("\033[H" + "\n".join(f"{line}\033[K" for line in screen) + "\033[J")
            out.flush()
            tick += 1
            time.sleep(REFRESH)
    except KeyboardInterrupt:
        pass
    finally:
        out.write("\033[?25h\033[?1049l")
        out.flush()
