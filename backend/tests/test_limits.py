import pytest

from green import limits
from green.limits import TilesOverLimitError, check_tiles, measure_tiles


def _files(tmp_path, sizes):
    paths = []
    for i, size in enumerate(sizes):
        path = tmp_path / "observed_ndvi" / f"2012-{i + 1:02d}.pmtiles"
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b"x" * size)
        paths.append(path)
    return paths


def test_measure_tiles_counts_files_and_finds_the_largest(tmp_path):
    paths = _files(tmp_path, [10, 30, 20])
    measured = measure_tiles(paths)
    assert measured.count == 3
    assert measured.total == 60
    assert measured.largest == (paths[1], 30)


def test_check_tiles_passes_within_the_limits(tmp_path):
    paths = _files(tmp_path, [10, 30, 20])
    assert check_tiles(paths).count == 3


def test_check_tiles_fails_on_too_many_files_for_a_release(tmp_path, monkeypatch):
    monkeypatch.setattr(limits, "RELEASE_MAX_ASSETS", 2)
    with pytest.raises(TilesOverLimitError, match=r"3 PMTiles files.*Release.*2"):
        check_tiles(_files(tmp_path, [1, 1, 1]))


def test_check_tiles_fails_on_a_file_too_big_for_a_release(tmp_path, monkeypatch):
    monkeypatch.setattr(limits, "RELEASE_MAX_ASSET_BYTES", 25)
    with pytest.raises(TilesOverLimitError, match=r"2012-02\.pmtiles.*30 B.*Release"):
        check_tiles(_files(tmp_path, [10, 30, 20]))


def test_check_tiles_fails_on_a_total_too_big_for_pages(tmp_path, monkeypatch):
    monkeypatch.setattr(limits, "PAGES_MAX_SITE_BYTES", 50)
    with pytest.raises(TilesOverLimitError, match=r"60 B.*Pages"):
        check_tiles(_files(tmp_path, [10, 30, 20]))


def test_check_tiles_reports_every_limit_it_is_over(tmp_path, monkeypatch):
    monkeypatch.setattr(limits, "RELEASE_MAX_ASSETS", 2)
    monkeypatch.setattr(limits, "PAGES_MAX_SITE_BYTES", 50)
    with pytest.raises(TilesOverLimitError) as error:
        check_tiles(_files(tmp_path, [10, 30, 20]))
    assert "Release" in str(error.value) and "Pages" in str(error.value)
    assert "docs.github.com" in str(error.value)
