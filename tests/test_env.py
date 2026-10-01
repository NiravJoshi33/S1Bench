import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_bench_owns_browser_name_even_if_you_exported_another():
    # A fresh interpreter: import-time behaviour can't be tested in a process that already imported it.
    code = "import s1bench; from browser_harness import helpers; print(helpers.NAME)"
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env={**os.environ, "BU_NAME": "my-real-chrome"},
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == "s1bench"
