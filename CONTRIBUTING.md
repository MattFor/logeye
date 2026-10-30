# Contributing to LogEye

Thanks for helping out! Bug reports with a minimal script are the most useful
thing of all; see the issue templates.

## Setup

LogEye has no runtime dependencies. Development uses [uv](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/MattFor/logeye
cd logeye
uv sync          # creates .venv with the dev tools
```

## Checks

CI runs all of these; please run them before opening a pull request.

```bash
uv run ruff format .        # formatting (tabs, double quotes)
uv run ruff check .         # lint
uv run basedpyright         # type-check, against Python 3.8
uv run pytest               # tests, demos included
```

LogEye supports Python 3.8 to 3.14. To run the tests on another version:

```bash
uv run --isolated --python 3.8 pytest   # leaves .venv alone
```

### Coverage

Coverage needs Python 3.12 or newer (it uses `sys.monitoring`), plus
`LOGEYE_MEASURE_TRACERS=1`: LogEye's own trace functions run with tracing switched
off, where no coverage tool can see them, and this runs them with it back on.

```bash
LOGEYE_MEASURE_TRACERS=1 COVERAGE_CORE=sysmon uv run coverage run -m pytest
uv run coverage combine     # the demos run in subprocesses
uv run coverage report      # fails under the threshold in pyproject.toml
```

## Ground rules

- **Logging must never change what the program computes.** LogEye only observes:
  it may swap in a logging copy of a container only when nothing else can hold a
  reference to it yet. `tests/test_semantics.py` guards this; add a test there for
  anything that touches how values are wrapped.
- Every bug fix comes with a regression test, usually in `tests/test_regressions.py`.
- Code must run on Python 3.8: no `X | Y` or `list[int]` outside annotations,
  typing-only names from `typing_extensions` under `TYPE_CHECKING`. basedpyright
  checks against 3.8 and catches most of it.

## Demos

The demos in `demos/` double as tests: `tests/test_demos.py` runs each one and
compares its output to `tests/demo_output/`. After an intended output change:

```bash
LOGEYE_UPDATE_DEMOS=1 uv run pytest tests/test_demos.py
```

and review the diff of `tests/demo_output/`.

## Releasing (maintainers)

There is no version to bump: it comes from the git tag.

1. Rename `## [Unreleased]` in `CHANGELOG.md` to `## [X.Y.Z] - HH:MM CEST DD-MM-YYYY`
   (keeping a new empty `## [Unreleased]` above it) and commit it as `Release vX.Y.Z`.
2. Tag it: `git tag -a vX.Y.Z -m vX.Y.Z && git push origin master vX.Y.Z`.
3. The release workflow runs every check, builds, publishes to PyPI and fills in
   the GitHub release with that changelog section.

Publishing uses PyPI [trusted publishing](https://docs.pypi.org/trusted-publishers/),
so no token is stored anywhere. One-time setup on pypi.org, under the project's
_Publishing_ settings: add a GitHub publisher with owner `MattFor`, repository
`logeye`, workflow `release.yml` and environment `pypi`.
