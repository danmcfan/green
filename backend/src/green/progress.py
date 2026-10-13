"""Progress logging for long runs: counts, percent, elapsed time and ETA."""

import logging
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# Seconds between progress lines, so a CONUS fetch of hundreds of chunks stays readable.
INTERVAL = 10.0


def _duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m{seconds % 60:02d}s"
    return f"{seconds // 3600}h{seconds // 60 % 60:02d}m"


class Progress:
    """Thread-safe counter that logs at most every INTERVAL seconds, and always at the end."""

    def __init__(self, label: str, total: int, interval: float = INTERVAL):
        self.label = label
        self.total = total
        self.interval = interval
        self.done = 0
        self.start = time.monotonic()
        self.last = self.start
        self.lock = threading.Lock()

    def advance(self, n: int = 1) -> None:
        with self.lock:
            self.done += n
            now = time.monotonic()
            if self.done < self.total and now - self.last < self.interval:
                return
            self.last = now
            elapsed = now - self.start
            line = f"{self.label}: {self.done}/{self.total} ({100 * self.done / self.total:.0f}%)"
            line += f", {_duration(elapsed)} elapsed"
            if self.done < self.total:
                line += f", ~{_duration(elapsed / self.done * (self.total - self.done))} left"
            logger.info(line)


@contextmanager
def step(name: str) -> Iterator[None]:
    """Log the start and duration of a pipeline step."""
    logger.info("▶ %s", name)
    start = time.monotonic()
    yield
    logger.info("✔ %s in %s", name, _duration(time.monotonic() - start))
