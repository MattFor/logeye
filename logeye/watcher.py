from __future__ import annotations

import os
import sys
import threading

from numbers import Real
from types import CodeType, FrameType
from collections.abc import Mapping

from typing import (
	TYPE_CHECKING,
	Callable,
	Literal,
	SupportsFloat,
	SupportsIndex,
	TypeVar,
	cast,
)

from logeye.emitter import _emit
from logeye.introspection import _is_library_file, _line_assigns, _line_may_mutate
from logeye.introspection.frames import _is_external_code

if TYPE_CHECKING:
	from _typeshed import TraceFunction
	from typing_extensions import TypeAlias, TypeGuard

	from .core import Kind

# Events sys.settrace dispatches
TraceEvent: TypeAlias = Literal["call", "line", "return", "exception", "opcode"]

_NO_VALUE: object = object()

# Cap on tracked code objects, bounding growth under exec / hot reload / closures
_MAX_TRACKED_CODES = 512

# How many any() passes to collapse an elementwise mask (ndarray, DataFrame)
_MAX_MASK_REDUCTIONS = 4

K = TypeVar("K")


def _slot(store: dict[CodeType, K], code: CodeType, factory: Callable[[], K]) -> K:
	"""Per-code-object state, evicting the oldest entries past the cap"""

	existing = store.get(code)
	if existing is not None:
		return existing

	if len(store) >= _MAX_TRACKED_CODES:
		# Insertion-ordered; front is oldest
		for stale in list(store)[: _MAX_TRACKED_CODES // 4]:
			del store[stale]

	fresh = factory()
	store[code] = fresh
	return fresh


# (code, name) -> the line an explicit log() / watch() already reported it on
_recently_emitted: dict[tuple[CodeType, str], int] = {}

_g_trace_installed: bool = False

# Whatever was installed before (pdb, coverage.py); chained to and restored
_g_previous_trace: TraceFunction | None = None

_g_watched_names: dict[CodeType, set[str]] = {}
_g_last_seen: dict[CodeType, dict[str, object]] = {}
_g_watch_meta: dict[CodeType, dict[str, dict[str, object]]] = {}

# frame -> last line seen; dropped on return so frames are not retained
_g_last_line: dict[FrameType, int] = {}

# frame -> the local trace function the chained tracer handed back for it
_g_chained_locals: dict[FrameType, TraceFunction] = {}

# Coverage tools cannot see code that runs inside a trace function: the interpreter
# switches tracing off there. The test suite sets this to measure logeye's own tracers,
# whose bodies then run through sys.call_tracing, which switches it back on
_MEASURE_TRACERS = bool(os.environ.get("LOGEYE_MEASURE_TRACERS"))

R = TypeVar("R")


# Set while a measured trace body runs on this thread
_measuring = threading.local()


def _measurable(
	trace: Callable[[FrameType, str, object], R],
) -> Callable[[FrameType, str, object], R]:
	if not _MEASURE_TRACERS:
		return trace

	def measured(frame: FrameType, event: str, arg: object) -> R:
		# Only events from user code are measured, and not those a measured body sets
		# off: it runs with tracing back on, so logeye's own frames, the stdlib and a
		# chained tracer all report here, and through sys.call_tracing again would
		# recurse without end
		filename = frame.f_code.co_filename
		if getattr(_measuring, "active", False) or _is_library_file(filename) or _is_external_code(filename):
			return trace(frame, event, arg)

		_measuring.active = True
		try:
			return sys.call_tracing(trace, (frame, event, arg))
		finally:
			_measuring.active = False

	return measured


def _mark_emitted(frame: FrameType, name: str) -> None:
	if not name:
		return

	if len(_recently_emitted) >= _MAX_TRACKED_CODES * 4:
		_recently_emitted.clear()

	_recently_emitted[(frame.f_code, name)] = frame.f_lineno


def _watch_threshold(code: CodeType, name: str) -> object | None:
	"""The threshold watch(..., threshold=) registered for `name` in this code"""

	return _g_watch_meta.get(code, {}).get(name, {}).get("threshold")


def _was_just_emitted(code: CodeType, name: str, lineno: int | None) -> bool:
	"""Did an explicit log() / watch() already report this name on this line?"""

	return lineno is not None and _recently_emitted.get((code, name)) == lineno


def _mark_watched(frame: FrameType, name: str, *, threshold: object | None = None) -> None:
	if not name or name == "_":
		return

	_slot(_g_watched_names, frame.f_code, set).add(name)

	if threshold is not None:
		_slot(_g_watch_meta, frame.f_code, dict)[name] = {
			"threshold": threshold,
		}


def _is_number(value: object) -> TypeGuard[Real]:
	# bool is a Real at runtime; it subclasses int
	return isinstance(value, Real) and not isinstance(value, bool)  # pyright: ignore[reportUnnecessaryIsInstance]


def _to_float(value: object) -> float:
	"""float() on a user value; it already raises on anything it cannot convert"""

	return float(cast("SupportsFloat | SupportsIndex | str | bytes", value))


def _is_single_threshold_spec(value: object) -> bool:
	if isinstance(value, (int, float)) and not isinstance(value, bool):
		return True

	if isinstance(value, tuple):
		# noinspection PyUnnecessaryCast
		parts = cast("tuple[object, ...]", value)
		if len(parts) == 2 and isinstance(parts[0], str):
			return parts[0] in {"absolute", "relative", "abs", "rel"}

	if isinstance(value, Mapping):
		# noinspection PyUnnecessaryCast
		keys = cast("Mapping[object, object]", value)
		return set(keys.keys()) <= {"absolute", "abs", "relative", "rel", "epsilon"}

	return False


def _normalize_threshold_spec(spec: object) -> dict[str, float]:
	if spec is None:
		return {}

	if isinstance(spec, (int, float)) and not isinstance(spec, bool):
		return {"absolute": float(spec)}

	if isinstance(spec, tuple):
		# noinspection PyUnnecessaryCast
		parts = cast("tuple[object, ...]", spec)

		if len(parts) == 2 and isinstance(parts[0], str):
			mode, value = parts[0], parts[1]

			if mode in {"absolute", "abs"}:
				return {"absolute": _to_float(value)}

			if mode in {"relative", "rel"}:
				return {"relative": _to_float(value)}

			raise TypeError(f"Unknown threshold mode: {mode!r}")

	if isinstance(spec, Mapping):
		# noinspection PyUnnecessaryCast
		mapping = cast("Mapping[object, object]", spec)

		out: dict[str, float] = {}
		if "absolute" in mapping:
			out["absolute"] = _to_float(mapping["absolute"])

		if "abs" in mapping:
			out["absolute"] = _to_float(mapping["abs"])

		if "relative" in mapping:
			out["relative"] = _to_float(mapping["relative"])

		if "rel" in mapping:
			out["relative"] = _to_float(mapping["rel"])

		if "epsilon" in mapping:
			out["epsilon"] = _to_float(mapping["epsilon"])

		return out

	raise TypeError("threshold must be a number, a ('absolute'|'relative', value) tuple, or a mapping!")


def _resolve_threshold_for_name(
	name: str,
	threshold: object | None,
) -> dict[str, float] | None:
	if threshold is None:
		return None

	# A global spec applies to every watched variable
	if _is_single_threshold_spec(threshold):
		return _normalize_threshold_spec(threshold)

	if isinstance(threshold, Mapping):
		# noinspection PyUnnecessaryCast
		per_name = cast("Mapping[object, object]", threshold)

		# Per-name mapping {"velocity": ("relative", 0.1), "hp": ("absolute", 1)}
		for candidate in (name, name.split(".")[-1]):
			if candidate in per_name:
				return _normalize_threshold_spec(per_name[candidate])

	return None


def _differs(old: object, new: object) -> bool:
	"""
	Did the value change?
	numpy arrays, pandas frames and friends answer `!=` with an elementwise mask
	that raises on bool(), so collapse it with any() until a real bool falls out.
	"""

	if old is new:
		return False

	try:
		result = old != new
	except Exception:
		return True

	for _ in range(_MAX_MASK_REDUCTIONS):
		try:
			return bool(result)
		except Exception:
			pass

		reducer = getattr(result, "any", None)
		if not callable(reducer):
			break

		try:
			result = reducer()
		except Exception:
			break

	return True


def _passes_threshold(old: object, new: object, threshold: dict[str, float] | None) -> bool:
	if old is _NO_VALUE:
		return True

	if threshold is None:
		return _differs(old, new)

	# Thresholds only for numbers
	if not (_is_number(old) and _is_number(new)):
		return _differs(old, new)

	delta = abs(float(new) - float(old))
	eps = threshold.get("epsilon", 1e-12)

	abs_th = threshold.get("absolute")
	if abs_th is not None and delta < abs_th:
		return False

	rel_th = threshold.get("relative")
	if rel_th is not None:
		base = max(abs(float(old)), eps)
		if delta / base < rel_th:
			return False

	return _differs(old, new)


def _forward(frame: FrameType, event: str, arg: object) -> None:
	"""
	Keep whatever tracer was installed before ours (pdb, coverage) working: it gets
	every "call", and the local trace function it asks for gets that frame's events
	"""

	# `event` is str so this also fits frame.f_trace, typed loosely
	trace_event = cast("TraceEvent", event)

	if event == "call":
		previous = _g_previous_trace
		if previous is None:
			return

		try:
			# noinspection PyCallingNonCallable
			local = previous(frame, trace_event, arg)
		except Exception:
			local = None

		if local is not None:
			_g_chained_locals[frame] = local

		return

	local = _g_chained_locals.get(frame)
	if local is None:
		return

	try:
		following = local(frame, trace_event, arg)
	except Exception:
		following = None

	if following is None or event == "return":
		_ = _g_chained_locals.pop(frame, None)
	else:
		_g_chained_locals[frame] = following


def _global_trace(frame: FrameType, event: str, arg: object) -> TraceFunction | None:
	"""Line tracer for names registered through watch() / log()"""

	_forward(frame, event, arg)

	watched = _g_watched_names.get(frame.f_code)
	if not watched:
		return _global_tracer if frame in _g_chained_locals else None

	if event not in ("line", "return"):
		return _global_tracer

	filename = frame.f_code.co_filename
	current = cast("Mapping[str, object]", frame.f_locals)
	last = _slot(_g_last_seen, frame.f_code, dict)
	meta = _g_watch_meta.get(frame.f_code)

	# Values seen on statement N's line event were produced by N-1
	lineno = _g_last_line.get(frame, frame.f_lineno)

	if event == "line":
		_g_last_line[frame] = frame.f_lineno
	else:
		_ = _g_last_line.pop(frame, None)

	for name in watched:
		if name == "_" or name not in current:
			continue

		if _was_just_emitted(frame.f_code, name, lineno):
			last[name] = current[name]  # Sync state
			continue

		value = current[name]
		old = last.get(name, _NO_VALUE)

		# A logging container reports its own changes; C code like heapq goes around them
		resync = getattr(type(value), "_logeye_resync", None) if old is value else None
		if callable(resync):
			if _line_may_mutate(filename, lineno, name):
				_ = resync(value, filename, lineno, name)
			continue

		differs = old is not _NO_VALUE and _differs(old, value)

		kind: Kind
		if old is _NO_VALUE:
			kind = "set"
		elif differs:
			kind = "change"
		elif _line_assigns(filename, lineno, name):
			# Written again with a value that compares equal; still an assignment
			kind = "change"
		else:
			continue

		threshold = _resolve_threshold_for_name(name, (meta or {}).get(name, {}).get("threshold"))

		if differs:
			if not _passes_threshold(old, value, threshold):
				continue
		elif old is not _NO_VALUE and threshold:
			continue

		_emit(kind, name, value, filename=filename, lineno=lineno)
		last[name] = value

	return _global_tracer


_global_tracer = _measurable(_global_trace)


def _is_call_tracer(trace: object) -> bool:
	"""Is `trace` the tracer of a @log call in progress? That call restores the trace itself"""

	code = getattr(trace, "__code__", None)

	return trace is not _global_tracer and isinstance(code, CodeType) and _is_library_file(code.co_filename)


def _install_global_trace(frame: FrameType | None = None) -> None:
	global _g_trace_installed, _g_previous_trace

	current = sys.gettrace()

	# A @log call in progress reports its own frames, watched names included
	if current is not _global_tracer and not _is_call_tracer(current):
		# Whatever was there keeps working through _forward, and comes back on uninstall
		_g_previous_trace = current
		sys.settrace(_global_tracer)

	_g_trace_installed = True

	# Frames already on the stack predate settrace and need f_trace set by hand,
	# unless something (a @log call, a debugger) traces them already
	while frame is not None:
		if frame.f_trace is None and frame.f_code in _g_watched_names:
			frame.f_trace = _global_tracer

			_ = _g_last_line.setdefault(frame, frame.f_lineno)

		frame = frame.f_back


def _uninstall_global_trace() -> None:
	"""Remove the watcher and restore what preceded it, so it does not outlive its use"""

	global _g_trace_installed, _g_previous_trace

	if not _g_trace_installed:
		return

	if sys.gettrace() is _global_tracer:
		sys.settrace(_g_previous_trace)

	_g_trace_installed = False
	_g_previous_trace = None


def _reset_watch_state() -> None:
	"""Forget everything the watcher has accumulated"""

	_g_watched_names.clear()
	_g_last_seen.clear()
	_g_watch_meta.clear()
	_g_last_line.clear()
	_g_chained_locals.clear()
	_recently_emitted.clear()


__all__ = [
	"TraceEvent",
	"_differs",
	"_global_tracer",
	"_install_global_trace",
	"_mark_emitted",
	"_mark_watched",
	"_measurable",
	"_passes_threshold",
	"_recently_emitted",
	"_reset_watch_state",
	"_resolve_threshold_for_name",
	"_uninstall_global_trace",
	"_was_just_emitted",
	"_watch_threshold",
]
