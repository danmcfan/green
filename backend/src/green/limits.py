"""GitHub Release and Pages limits that the PMTiles must fit within (ADR 0001, 0002, 0003).

Every PMTiles file is one Release asset, and Deploy copies every asset into the Pages site,
so the file count, the largest file and the total size are each checked here.
"""

from dataclasses import dataclass
from pathlib import Path

# "Each file included in a release must be under 2 GiB ... a limit of 1000 assets per release."
RELEASE_MAX_ASSETS = 1000
RELEASE_MAX_ASSET_BYTES = 2 * 1024**3
RELEASES_DOCS = "https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases#storage-and-bandwidth-quotas"

# "Published GitHub Pages sites may be no larger than 1 GB." The site's own build is small
# next to the tiles, so the tiles alone are held to this.
PAGES_MAX_SITE_BYTES = 1000**3
PAGES_DOCS = (
    "https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits"
)


class TilesOverLimitError(Exception):
    """The PMTiles would not fit in a GitHub Release or on GitHub Pages."""


@dataclass(frozen=True)
class TileSizes:
    count: int
    total: int
    largest: tuple[Path, int] | None

    def __str__(self) -> str:
        largest = f", largest {_size(self.largest[1])}" if self.largest else ""
        return f"{self.count} PMTiles files, {_size(self.total)} in all{largest}"


def _size(n: int) -> str:
    for unit in ("B", "KB", "MB"):
        if n < 1000:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1000
    return f"{n:.2f} GB"


def measure_tiles(paths: list[Path]) -> TileSizes:
    sizes = [(path, path.stat().st_size) for path in paths]
    largest = max(sizes, key=lambda s: s[1], default=None)
    return TileSizes(count=len(sizes), total=sum(s for _, s in sizes), largest=largest)


def check_tiles(paths: list[Path]) -> TileSizes:
    """Measure the PMTiles files and raise TilesOverLimitError if any GitHub limit is passed."""
    measured = measure_tiles(paths)
    problems = []
    if measured.count > RELEASE_MAX_ASSETS:
        problems.append(
            f"{measured.count} PMTiles files is more than a GitHub Release can hold "
            f"({RELEASE_MAX_ASSETS} assets; {RELEASES_DOCS})"
        )
    if measured.largest and measured.largest[1] >= RELEASE_MAX_ASSET_BYTES:
        path, size = measured.largest
        problems.append(
            f"{path} is {_size(size)}; each GitHub Release asset must be under "
            f"{_size(RELEASE_MAX_ASSET_BYTES)} ({RELEASES_DOCS})"
        )
    if measured.total > PAGES_MAX_SITE_BYTES:
        problems.append(
            f"the PMTiles total {_size(measured.total)}; a GitHub Pages site may be no larger "
            f"than {_size(PAGES_MAX_SITE_BYTES)} ({PAGES_DOCS})"
        )
    if problems:
        raise TilesOverLimitError(
            f"{measured} do not fit on GitHub:\n" + "\n".join(f"- {p}" for p in problems)
        )
    return measured
