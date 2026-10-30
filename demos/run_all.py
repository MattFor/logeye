"""
Run every demo in order: the whole tour of LogEye in one go.

    python demos/run_all.py

Works from a fresh checkout without installing anything; exits non-zero if any
demo fails, which is how CI keeps them all working.
"""

import os
import subprocess
import sys

from pathlib import Path

DEMOS = Path(__file__).resolve().parent
ROOT = DEMOS.parent


def main() -> int:
	env = dict(os.environ)
	# Import logeye from this checkout, installed or not
	env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(ROOT), env.get("PYTHONPATH")]))

	failed = []

	for demo in sorted(DEMOS.glob("[0-9][0-9]_*.py")):
		print(f"\n{'=' * 20} {demo.name} {'=' * 20}", flush=True)

		if subprocess.run([sys.executable, str(demo)], env=env).returncode != 0:
			failed.append(demo.name)

	if failed:
		print(f"\nFailed: {', '.join(failed)}", file=sys.stderr)

	return 1 if failed else 0


if __name__ == "__main__":
	sys.exit(main())
