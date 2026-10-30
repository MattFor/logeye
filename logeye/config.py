from __future__ import annotations

import os
import time
import threading

from typing import TYPE_CHECKING, Callable, Literal, Optional, Tuple

if TYPE_CHECKING:
	from typing_extensions import TypeAlias

PathMode: TypeAlias = Literal["absolute", "project", "file"]

Mode: TypeAlias = Literal["edu", "educational", "full"]

_g_enabled: bool = True

# Stamps measure from import / program start
_g_start_time: float = time.perf_counter()

# absolute -> full path | project -> relative to root | file -> basename
_g_path_mode: PathMode = "file"

# Whether message logs include timestamp + file info
_g_show_message_meta: bool = True
_g_deco_only: bool = False

# Process-wide defaults; per-call overrides live on _tls
_g_log_mode: Mode = "full"  # "full" | "educational"

_g_show_time: bool = True
_g_show_file: bool = True
_g_show_lineno: bool = True

_g_project_root: str = os.getcwd()
_g_library_root: str = os.path.dirname(__file__)

_g_log_pipe_name: str = "l"

_g_log_file: str | None = None
_g_log_file_enabled: bool = True


# ======================
#  PER-THREAD OVERRIDES
# ======================


class _ThreadState(threading.local):
	mode: Mode | None = None
	show_time: bool | None = None
	show_file: bool | None = None
	show_lineno: bool | None = None

	# Destination for everything logged while this call is on the stack
	filepath: str | None = None

	# level= / filter= of the enclosing @log, asked before change tracking emits
	emit_gate: Callable[[str, str], bool] | None = None


_tls: _ThreadState = _ThreadState()

# What _push_display saves and _pop_display restores
# typing.Tuple / Optional, not tuple[...] / X | None, so 3.8 can evaluate it
DisplayState: TypeAlias = Tuple[
	Optional[Mode],
	Optional[bool],
	Optional[bool],
	Optional[bool],
	Optional[str],
	Optional[Callable[[str, str], bool]],
]


def _mode() -> Mode:
	override = _tls.mode
	return _g_log_mode if override is None else override


def _show_time() -> bool:
	override = _tls.show_time
	return _g_show_time if override is None else override


def _show_file() -> bool:
	override = _tls.show_file
	return _g_show_file if override is None else override


def _show_lineno() -> bool:
	override = _tls.show_lineno
	return _g_show_lineno if override is None else override


EmitContext: TypeAlias = Tuple[bool, bool, bool, Optional[str], Optional[Callable[[str, str], bool]]]


def _emit_context(
	show_time: bool | None,
	show_file: bool | None,
	show_lineno: bool | None,
	filepath: str | None,
) -> EmitContext:
	"""Fill in whatever the caller left open from the call on the stack"""

	state = _tls

	if show_time is None:
		show_time = _g_show_time if state.show_time is None else state.show_time

	if show_file is None:
		show_file = _g_show_file if state.show_file is None else state.show_file

	if show_lineno is None:
		show_lineno = _g_show_lineno if state.show_lineno is None else state.show_lineno

	if filepath is None:
		filepath = state.filepath

	return show_time, show_file, show_lineno, filepath, state.emit_gate


def _push_display(
	mode: Mode | None = None,
	show_time: bool | None = None,
	show_file: bool | None = None,
	show_lineno: bool | None = None,
	filepath: str | None = None,
	emit_gate: Callable[[str, str], bool] | None = None,
) -> DisplayState:
	"""Install per-call overrides; pair with _pop_display in a finally"""

	previous: DisplayState = (
		_tls.mode,
		_tls.show_time,
		_tls.show_file,
		_tls.show_lineno,
		_tls.filepath,
		_tls.emit_gate,
	)

	_tls.mode = mode
	_tls.show_time = show_time
	_tls.show_file = show_file
	_tls.show_lineno = show_lineno
	_tls.filepath = filepath
	_tls.emit_gate = emit_gate

	return previous


def _reset_display() -> None:
	"""Forget every per-call override, whatever the state is made of"""

	_tls.mode = None
	_tls.show_time = None
	_tls.show_file = None
	_tls.show_lineno = None
	_tls.filepath = None
	_tls.emit_gate = None


def _pop_display(previous: DisplayState) -> None:
	(
		_tls.mode,
		_tls.show_time,
		_tls.show_file,
		_tls.show_lineno,
		_tls.filepath,
		_tls.emit_gate,
	) = previous


# =========
#  TOGGLES
# =========


def toggle_logs(enabled: bool) -> None:
	global _g_enabled
	_g_enabled = enabled


def toggle_global_log_file(enabled: bool) -> None:
	global _g_log_file_enabled
	_g_log_file_enabled = enabled


def toggle_decorator_log_only(enabled: bool) -> None:
	"""Toggle only @log-decorated tracing"""

	global _g_deco_only
	_g_deco_only = enabled


def toggle_message_metadata(enabled: bool) -> None:
	"""
	Enable or disable metadata for message logs
	Off: log("hello") -> "hello". On: log("hello") -> "[time] file:line hello"
	"""

	global _g_show_message_meta
	_g_show_message_meta = enabled


# =========
#  SETTERS
# =========


def set_mode(mode: Mode) -> None:
	"""Set global logging mode: full, or edu / educational"""

	global _g_log_mode
	_g_log_mode = _normalize_mode(mode)


def set_global_log_file(filepath: str | None) -> None:
	"""Route LogEye output to this file globally"""
	global _g_log_file
	_g_log_file = None if filepath is None else os.fspath(filepath)


def set_path_mode(mode: PathMode) -> None:
	global _g_path_mode

	if mode not in ("absolute", "project", "file"):
		raise ValueError(  # pyright: ignore[reportUnreachable]
			"mode must be: absolute, project, file"
		)

	_g_path_mode = mode


def _normalize_mode(mode: Mode) -> Mode:
	if mode in ("edu", "educational"):
		return "educational"

	if mode == "full":
		return "full"

	raise ValueError(  # pyright: ignore[reportUnreachable]
		"mode must be: full, edu, educational"
	)


__all__ = [
	"DisplayState",
	"Mode",
	"PathMode",
	"_emit_context",
	"_mode",
	"_normalize_mode",
	"_pop_display",
	"_push_display",
	"_reset_display",
	"_show_file",
	"_show_lineno",
	"_show_time",
	"set_global_log_file",
	"set_mode",
	"set_path_mode",
	"toggle_decorator_log_only",
	"toggle_global_log_file",
	"toggle_logs",
	"toggle_message_metadata",
]
