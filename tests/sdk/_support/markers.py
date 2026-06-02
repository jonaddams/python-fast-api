"""xfail helper that links a known defect to docs/sdk-feedback/DEFECTS.md."""
import pytest


def defect(defect_id: str, reason: str, *, raises=None):
    """Mark a test as a KNOWN SDK defect.

    strict=True: when the SDK is fixed the test xpasses and the suite goes RED,
    prompting removal of the marker and a DEFECTS.md status update.
    """
    return pytest.mark.xfail(
        reason=f"{defect_id}: {reason}",
        strict=True,
        raises=raises,
    )
