## What and why

<!-- What does this change, and what problem does it solve? Link the issue if there is one. -->

## Checklist

- [ ] Tests cover the change (`uv run pytest`)
- [ ] `uv run ruff format . && uv run ruff check . && uv run basedpyright` pass
- [ ] If the output of a demo changed on purpose: `LOGEYE_UPDATE_DEMOS=1 uv run pytest tests/test_demos.py`
- [ ] `CHANGELOG.md` has an entry under `[Unreleased]`
