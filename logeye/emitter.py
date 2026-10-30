from __future__ import annotations

import os
import time
import atexit
import contextlib

from typing import TYPE_CHECKING, TextIO

from . import config

# The module, not the name; binding _formatter here would freeze it at import
from . import formatting
from .introspection import _is_user_code

if TYPE_CHECKING:
	from .core import Kind

_open_files: dict[str, TextIO] = {}


def _handle_for(filepath: str) -> TextIO:
	handle = _open_files.get(filepath)
	if handle is not None and not handle.closed:
		return handle

	directory = os.path.dirname(filepath)
	if directory:
		os.makedirs(directory, exist_ok=True)

	handle = open(filepath, "a", encoding="utf-8")  # noqa: SIM115 -- kept open for later lines, closed at exit
	_open_files[filepath] = handle
	return handle


def _write_line_to_file(filepath: str, line: str) -> None:
	handle = _handle_for(filepath)
	_ = handle.write(line + "\n")
	handle.flush()


def _close_log_files() -> None:
	for handle in _open_files.values():
		with contextlib.suppress(OSError):
			handle.close()

	_open_files.clear()


def clear_log_file(*filepaths: str) -> None:
	targets = list(filepaths) if filepaths else list(_open_files)

	for filepath in targets:
		path = os.fspath(filepath)

		handle = _open_files.pop(path, None)
		if handle is not None and not handle.closed:
			with contextlib.suppress(OSError):
				handle.close()

		directory = os.path.dirname(path)
		if directory:
			os.makedirs(directory, exist_ok=True)

		try:
			with open(path, "w", encoding="utf-8"):
				pass
		except OSError:
			pass


_ = atexit.register(_close_log_files)


def _emit(
	kind: Kind,
	name: str,
	value: object,
	*,
	filename: str | None = None,
	lineno: int | None = None,
	filepath: str | None = None,
	show_time: bool | None = None,
	show_file: bool | None = None,
	show_lineno: bool | None = None,
	tracked: bool = False,
) -> None:
	"""Render one event and put it wherever the call on the stack wants it"""

	if not config._g_enabled:
		return

	if filename and not _is_user_code(filename):
		return

	show_time, show_file, show_lineno, filepath, gate = config._emit_context(
		show_time, show_file, show_lineno, filepath
	)

	if tracked and gate is not None and not gate(kind, name):
		return

	is_edu = config._mode() == "educational"

	if is_edu:
		payload = formatting._payload_of(value)

		if (
			kind == "change"
			and payload is not None
			and payload.get("op") == "extend"
			and not payload.get("value")
			and not payload.get("observed")
		):
			return

		filename = None
		lineno = None

	elapsed = time.perf_counter() - config._g_start_time

	positional, takes_flags = formatting._formatter_shape
	arguments: tuple[object, ...] = (elapsed, kind, name, value, filename, lineno)[:positional]

	try:
		if takes_flags:
			line = formatting._formatter(
				*arguments,
				show_time=show_time,
				show_file=show_file,
				show_lineno=show_lineno,
			)
		else:
			line = formatting._formatter(*arguments)
	except Exception as exc:
		# A repr() or a custom formatter that raises must not crash the program it logs
		line = f"[logeye] could not format {kind} {name}: {type(exc).__name__}"

	# Educational mode dropped it
	if not line:
		return

	if filepath is not None:
		_write_line_to_file(filepath, line)
		return

	if config._g_log_file_enabled and config._g_log_file:
		_write_line_to_file(config._g_log_file, line)
		return

	print(line)


__all__ = ["_emit", "clear_log_file"]
