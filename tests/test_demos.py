"""
Every demo runs cleanly and prints what tests/demo_output/ says it prints.
Timestamps, file locations and memory addresses vary between runs and are
normalised away; the rest is compared exactly, on every supported Python.

After an intended output change, regenerate the expected files with:

    LOGEYE_UPDATE_DEMOS=1 pytest tests/test_demos.py
"""

import os
import re
import subprocess
import sys

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
EXPECTED = Path(__file__).resolve().parent / "demo_output"
DEMOS = sorted((ROOT / "demos").glob("[0-9][0-9]_*.py"))

_TIMESTAMP = re.compile(r"\[\d+\.\d+s\] ")
_LOCATION = re.compile(r"[\w.:/\\-]+\.py:\d+ ")
_ADDRESS = re.compile(r"0x[0-9a-fA-F]+")


def _normalise(output: str) -> str:
	output = _TIMESTAMP.sub("", output)
	output = _LOCATION.sub("", output)
	return _ADDRESS.sub("0x?", output)


@pytest.mark.parametrize("demo", DEMOS, ids=[demo.stem for demo in DEMOS])
def test_demo_output(demo):
	env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONHASHSEED="0", PYTHONIOENCODING="utf-8")

	result = subprocess.run(
		[sys.executable, str(demo)],
		cwd=ROOT,
		env=env,
		capture_output=True,
		text=True,
		encoding="utf-8",
		timeout=60,
	)

	assert result.returncode == 0, result.stderr
	assert result.stderr == "", result.stderr

	actual = _normalise(result.stdout)
	expected_file = EXPECTED / f"{demo.stem}.txt"

	if os.environ.get("LOGEYE_UPDATE_DEMOS"):
		EXPECTED.mkdir(exist_ok=True)
		expected_file.write_text(actual, encoding="utf-8")

	assert actual == expected_file.read_text(encoding="utf-8")


def test_every_demo_has_expected_output():
	assert sorted(path.stem for path in EXPECTED.glob("*.txt")) == [demo.stem for demo in DEMOS]
