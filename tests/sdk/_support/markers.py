"""xfail helper that links a known defect to docs/sdk-feedback/DEFECTS.md."""
import os

import pytest

# Tests that deliberately crash a child process (the SDK-034/035 fork-safety
# reproductions) trigger a macOS "Python quit unexpectedly" dialog on every
# run. Skip them by default; set SDK_FORK_CRASH_TESTS=1 to run them.
fork_crash = pytest.mark.skipif(
    not os.environ.get("SDK_FORK_CRASH_TESTS"),
    reason="crashes a child process by design (macOS crash dialog); set SDK_FORK_CRASH_TESTS=1 to run",
)


def defect(defect_id: str, reason: str, *, raises=None):
    """Mark a test as a KNOWN SDK defect.

    Applies the `sdk_defect` marker (so `pytest -m sdk_defect` selects these)
    AND a strict xfail. strict=True means a fixed SDK turns the test XPASS ->
    suite RED, prompting removal of the marker and a DEFECTS.md status update.
    """
    xfail_mark = pytest.mark.xfail(
        reason=f"{defect_id}: {reason}",
        strict=True,
        raises=raises,
    )

    def wrap(func):
        return pytest.mark.sdk_defect(xfail_mark(func))

    return wrap
