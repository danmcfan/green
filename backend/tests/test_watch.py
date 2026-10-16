from green.watch import ANSI, parse, render

LOG = """task: [pipeline] uv run green run --region conus --start 2012 --end 2013
[2026-10-16 10:08:08] INFO - ▶ Run 2012–2013
[2026-10-16 10:08:08] INFO - ▶ Extract
[2026-10-16 10:08:08] INFO - Using saved soil
[2026-10-16 10:08:09] INFO - Extracting 2013 (year 2 of 2)
[2026-10-16 10:08:09] INFO - Fetching climate 2013: 84 bands over 55 chunks
[2026-10-16 10:08:15] WARNING - climate 2013: chunk 128 × 128 too large, splitting
[2026-10-16 10:08:24] INFO - climate 2013: 11/55 (20%), 10s elapsed, ~40s left
[2026-10-16 10:18:24] WARNING - Sleeping 0.04 seconds before retry 1 of 1 for: x, after 503
[2026-10-16 10:18:25] WARNING - Sleeping 1.52 seconds before retry 1 of 1 for: x, after 503
""".splitlines()


def test_parse_follows_downloads_and_problems():
    run = parse(LOG)
    assert run.steps == ["Run 2012–2013", "Extract"]
    assert run.year == (2013, 2, 2)
    assert run.downloads["soil"].saved
    climate = run.current
    assert (climate.name, climate.done, climate.total, climate.eta) == (
        "climate 2013",
        11,
        55,
        "40s",
    )
    assert run.warnings == 3 and run.errors == 0
    # Repeated retries collapse into one line with a count.
    assert run.problems[-1].message == "request retried after 503"
    assert run.problems[-1].count == 2
    assert not run.failed


def test_a_failed_run_keeps_its_last_output():
    run = parse(
        [
            *LOG,
            "Traceback (most recent call last):",
            "  File x",
            "ee.ee_exception.EEException: User memory limit exceeded.",
            'task: Failed to run task "pipeline": exit status 1',
        ]
    )
    assert run.failed and run.errors == 1
    assert "User memory limit exceeded." in run.failure[-1]


def test_a_finished_download_is_not_current():
    run = parse([*LOG, "[2026-10-16 10:20:00] INFO - climate 2013: 55/55 (100%), 12m elapsed"])
    assert run.current is None and run.downloads["climate 2013"].finished


def test_render_fills_the_screen_without_wrapping():
    for width, height in [(60, 20), (140, 50)]:
        screen = render(parse(LOG), width, height, True, 3.0, 0, "run.log")
        assert len(screen) == height - 1
        assert all(len(ANSI.sub("", line)) < width for line in screen)
