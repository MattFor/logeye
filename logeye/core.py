from __future__ import annotations

import sys
import inspect
import contextlib
import warnings
import functools

from types import CellType, CodeType, FrameType
from collections import deque
from dataclasses import dataclass
from collections.abc import (
	AsyncGenerator,
	Awaitable,
	Callable,
	Generator,
	Iterable,
	Mapping,
)
from typing import TYPE_CHECKING, Dict, Literal, TypeVar, cast, overload

from . import config
from .emitter import _emit
from .formatting import _path, _safe_repr
from .introspection.ast import (
	_observed_call,
	_comprehension_variables,
	_fresh_binding,
	_get_constructed_target,
	_line_may_mutate,
	_infer_name_from_frame,
	_get_assignment_target_for_call,
)
from .introspection.templates import _expand_template, _format_message
from .wrappers import (
	_OPAQUE_TYPES,
	_BaseLogged,
	_unwrap_value,
	_wrap_value,
	_wrap_assigned,
	_observed_change,
	LoggedDict,
	LoggedObject,
)
from .introspection.frames import (
	_caller_frame,
	_get_location,
	_is_library_file,
	_is_external_code,
)
from .watcher import (
	_differs,
	_mark_emitted,
	_mark_watched,
	_passes_threshold,
	_watch_threshold,
	_was_just_emitted,
	_measurable,
	_install_global_trace,
	_resolve_threshold_for_name,
)

if TYPE_CHECKING:
	from _typeshed import TraceFunction
	from typing_extensions import ParamSpec

	from .config import Mode

	P = ParamSpec("P")

_NO_VALUE: object = object()


@dataclass
class _CallState:
	"""What one traced invocation needs to report its own exit"""

	tracer: TraceFunction
	name: str
	signature: str
	should_emit: Callable[[str, str], bool]

	# Arguments as displayed: a method's self / cls left out
	args: tuple[object, ...]
	kwargs: dict[str, object]

	# Line the frame last stopped on, filled in as a generator suspends
	exit_line: int | None = None

	# Where the call was written, for exits the tracer never gets to see
	call_filename: str | None = None
	call_lineno: int | None = None

	# Did sys.settrace ever hand a frame for this call?
	traced: bool = False


T = TypeVar("T")
K = TypeVar("K")
V = TypeVar("V")

Level = Literal["call", "state", "full"]
Kind = Literal["change", "message", "set", "call", "return", "raise", "yield"]

# Not user logic; comprehensions are their own frames before 3.12
_SKIPPED_NESTED_NAMES = frozenset(
	{
		"currentframe",
		"abspath",
		"join",
		"parse",
		"<listcomp>",
		"<setcomp>",
		"<dictcomp>",
		"<genexpr>",
	}
)

# C types reject attribute assignment: 3.10+ flags them immutable, and before
# that only heap types (classes created at runtime) could be patched at all
_Py_TPFLAGS_IMMUTABLETYPE = 1 << 8
_Py_TPFLAGS_HEAPTYPE = 1 << 9

# Values a local is compared against a snapshot of, to see changes made in place
_CONTAINERS = (list, dict, set)

# Code that suspends and resumes on an event loop's schedule rather than its caller's
_ASYNC_CODE = inspect.CO_COROUTINE | inspect.CO_ASYNC_GENERATOR | inspect.CO_ITERABLE_COROUTINE


class _Driven:
	"""Makes a driver generator awaitable from an async def"""

	__slots__: tuple[str, ...] = ("_steps",)

	def __init__(self, steps: Generator[object, object, object]) -> None:
		self._steps: Generator[object, object, object] = steps

	def __await__(self) -> Generator[object, object, object]:
		return self._steps


class _Attributes(Dict[str, object]):
	"""Snapshot of a plain object's public attributes, diffed one attribute at a time"""


def _comparable(value: object) -> object:
	"""A deque is compared as a list; the two never compare equal"""

	# noinspection PyUnnecessaryCast
	return list(cast("deque[object]", value)) if isinstance(value, deque) else value


def _snapshot(value: object) -> object:
	"""A plain copy to diff `value` against later; _NO_VALUE when it reports itself"""

	if isinstance(value, _BaseLogged):
		return _NO_VALUE

	if isinstance(value, _CONTAINERS):
		return _unwrap_value(cast(object, value))

	if isinstance(value, deque):
		# Kept as a list, which is what a deque is compared as; the two never compare equal
		# noinspection PyUnnecessaryCast
		return [_unwrap_value(item) for item in cast("deque[object]", value)]

	attributes = getattr(value, "__dict__", None)

	if (
		type(attributes) is dict
		and not callable(value)
		and not isinstance(value, _OPAQUE_TYPES)
		# A @log class reports its own attributes
		and not getattr(type(value).__setattr__, "_logeye_patched", False)
	):
		# noinspection PyUnnecessaryCast
		items = cast("dict[str, object]", attributes).items()
		return _Attributes({k: _unwrap_value(v) for k, v in items if not k.startswith("_")})

	return _NO_VALUE


def _resolve_filepath(file: str | None = None, filepath: str | None = None) -> str | None:
	if file is not None and filepath is not None:
		raise TypeError("Use only one of 'file' or 'filepath'")
	return file if file is not None else filepath


# ===============
#  CLASS LOGGING
# ===============


def _wrap_class_methods(
	cls: type,
	logged_cls: type,
	*,
	filepath: str | None,
	level: Level,
	mode: Mode,
	show_time: bool,
	show_file: bool,
	show_lineno: bool,
) -> None:
	# noinspection PyUnnecessaryCast
	members = cast("dict[str, object]", dict(cls.__dict__))

	for attr_name, attr_value in members.items():
		if attr_name in {
			"__module__",
			"__doc__",
			"__annotations__",
			"__dict__",
			"__weakref__",
			"__init__",
		}:
			continue

		if attr_name.startswith("__") and attr_name.endswith("__"):
			continue

		wrapped: object

		if isinstance(attr_value, staticmethod):
			wrapped = staticmethod(
				_log_function(
					attr_value.__func__,
					filepath=filepath,
					level=level,
					mode=mode,
					show_time=show_time,
					show_file=show_file,
					show_lineno=show_lineno,
				)
			)
		elif isinstance(attr_value, classmethod):
			# noinspection PyUnnecessaryCast
			wrapped = classmethod(
				_log_function(
					cast("classmethod[object, ..., object]", attr_value).__func__,
					filepath=filepath,
					level=level,
					mode=mode,
					show_time=show_time,
					show_file=show_file,
					show_lineno=show_lineno,
				)
			)
		elif inspect.isfunction(attr_value):
			wrapped = _log_function(
				cast("Callable[..., object]", attr_value),
				filepath=filepath,
				level=level,
				mode=mode,
				show_time=show_time,
				show_file=show_file,
				show_lineno=show_lineno,
			)
		else:
			continue

		setattr(logged_cls, attr_name, wrapped)


def _instance_label(instance: object) -> str:
	return getattr(instance, "_logeye_name", None) or type(instance).__name__.lower()


def _is_patchable(cls: type) -> bool:
	"""Can attributes be assigned on `cls`? C types refuse"""

	flags = cls.__flags__
	return bool(flags & _Py_TPFLAGS_HEAPTYPE) and not flags & _Py_TPFLAGS_IMMUTABLETYPE


def _user_stacklevel() -> int:
	"""How far `warnings.warn` must climb to blame the caller's line"""

	try:
		frame = sys._getframe(1)
	except ValueError:
		return 1

	try:
		level = 1

		while frame is not None:
			if not _is_library_file(frame.f_code.co_filename):
				return level

			frame = frame.f_back
			level += 1

		return 1
	finally:
		del frame


def _log_class(
	cls: type,
	*,
	filepath: str | None = None,
	level: Level = "full",
	mode: Mode = "full",
	show_time: bool = True,
	show_file: bool = True,
	show_lineno: bool = True,
) -> type:
	"""
	Instrument a class so instances report construction and attribute changes
	Patched in place rather than subclassed, so `type(obj) is cls` keeps holding
	"""

	if not _is_patchable(cls):
		warnings.warn(
			f"logeye cannot instrument the C type {cls.__qualname__!r}; it is returned unchanged",
			RuntimeWarning,
			stacklevel=_user_stacklevel(),
		)
		return cls

	original_init = cast("Callable[..., None]", cls.__init__)
	original_setattr = cast("Callable[[object, str, object], None]", cast(object, cls.__setattr__))
	original_delattr = cast("Callable[[object, str], None]", cast(object, cls.__delattr__))

	qualname = cls.__qualname__.replace(".<locals>.", ".")

	# __slots__ classes have nowhere to park the display name
	supports_instance_dict = any(
		"__dict__" in vars(base) or "__slots__" not in vars(base) for base in cls.__mro__ if base is not object
	)

	def _run_init(self: object, args: tuple[object, ...], kwargs: dict[str, object]) -> None:
		if original_init is not object.__init__:
			original_init(self, *args, **kwargs)
		# Patching __init__ stops object.__new__ rejecting arguments; reject them here
		elif (args or kwargs) and type(self).__new__ is object.__new__:
			raise TypeError(f"{type(self).__qualname__}() takes no arguments")
		else:
			# Whatever __new__ consumed them; object.__init__ would now refuse them
			original_init(self)

	@functools.wraps(original_init)
	def __init__(self: object, *args: object, **kwargs: object) -> None:
		if not config._g_enabled:
			_run_init(self, args, kwargs)
			return

		call_frame = _caller_frame()
		call_filename, call_lineno = _get_location(call_frame)

		# `x = log(Foo())`, then `x = Foo()`, then the class name
		instance_name = (
			_get_assignment_target_for_call(call_frame)
			or _get_constructed_target(call_frame, type(self).__name__)
			or type(self).__name__.lower()
		)

		if supports_instance_dict:
			with contextlib.suppress(AttributeError):
				object.__setattr__(self, "_logeye_name", instance_name)

		previous = config._push_display(mode, show_time, show_file, show_lineno, filepath)

		try:
			_emit(
				"call",
				f"{qualname}.__init__",
				{
					"type": "class_init",
					"class_name": qualname,
					"target": instance_name,
					"instance_name": instance_name,
					"args": args,
					"kwargs": kwargs,
				},
				filename=call_filename,
				lineno=call_lineno,
				filepath=filepath,
				show_time=show_time,
				show_file=show_file,
				show_lineno=show_lineno,
			)
		finally:
			config._pop_display(previous)

		_run_init(self, args, kwargs)

	def __setattr__(self: object, name: str, value: object) -> None:
		if not config._g_enabled or name == "_logeye_name":
			original_setattr(self, name, value)
			return

		is_private = name.startswith("_")
		instance_name = _instance_label(self)

		already_exists = name in getattr(self, "__dict__", ())

		original_setattr(self, name, _wrap_assigned(value, f"{instance_name}.{name}"))

		frame = _caller_frame()
		try:
			display_value = value
			filename, lineno = _get_location(frame)

			if is_private:
				display_value = {"type": "private", "value": value}

			kind = "change" if already_exists else "set"

			previous = config._push_display(mode, show_time, show_file, show_lineno, filepath)

			try:
				_emit(
					kind,
					f"{instance_name}.{name}",
					display_value,
					filename=filename,
					lineno=lineno,
					filepath=filepath,
					show_time=show_time,
					show_file=show_file,
					show_lineno=show_lineno,
				)
			finally:
				config._pop_display(previous)

			if frame is not None:
				_mark_emitted(frame, f"{instance_name}.{name}")
		finally:
			del frame

	def __delattr__(self: object, name: str) -> None:
		instance_name = _instance_label(self)

		original_delattr(self, name)

		if not config._g_enabled:
			return

		frame = _caller_frame()
		try:
			filename, lineno = _get_location(frame)

			previous = config._push_display(mode, show_time, show_file, show_lineno, filepath)

			try:
				_emit(
					"set",
					f"{instance_name}.{name}",
					"<deleted>",
					filename=filename,
					lineno=lineno,
					filepath=filepath,
					show_time=show_time,
					show_file=show_file,
					show_lineno=show_lineno,
				)
			finally:
				config._pop_display(previous)

			if frame is not None:
				_mark_emitted(frame, f"{instance_name}.{name}")
		finally:
			del frame

	_wrap_class_methods(
		cls,
		cls,
		filepath=filepath,
		level=level,
		mode=mode,
		show_time=show_time,
		show_file=show_file,
		show_lineno=show_lineno,
	)

	for attr, patched in (
		("__init__", __init__),
		("__setattr__", __setattr__),
		("__delattr__", __delattr__),
	):
		# Inherited from a @log base, which already reports it; a second layer would double up
		if getattr(cast(object, getattr(cls, attr)), "_logeye_patched", False):
			continue

		setattr(patched, "_logeye_patched", True)  # noqa: B010 -- not an attribute of the function's type
		setattr(cls, attr, patched)

	return cls


def _emit_named_or_message(
	name: str | None,
	value: object,
	*,
	frame: FrameType | None,
	filename: str | None,
	lineno: int | None,
	show_time: bool,
	show_file: bool,
	show_lineno: bool,
) -> None:
	"""
	Log a value under the name it was assigned to, or as a bare message
	A bare `log(value)` statement has no target, so there is nothing to name
	"""

	if not name:
		_emit(
			"message",
			"message",
			value,
			filename=filename,
			lineno=lineno,
			show_time=show_time,
			show_file=show_file,
			show_lineno=show_lineno,
		)
		return

	_emit(
		"set",
		name,
		value,
		filename=filename,
		lineno=lineno,
		show_time=show_time,
		show_file=show_file,
		show_lineno=show_lineno,
	)

	if frame is not None:
		_mark_emitted(frame, name)


# =====================
# WATCH (value logging)
# =====================


@overload
def watch(
	value: Callable[P, T],
	name: str | None = ...,
	*,
	threshold: object | None = ...,
	show_time: bool = ...,
	show_file: bool = ...,
	show_lineno: bool = ...,
) -> Callable[P, T]: ...


@overload
def watch(
	value: T,
	name: str | None = ...,
	*,
	threshold: object | None = ...,
	show_time: bool = ...,
	show_file: bool = ...,
	show_lineno: bool = ...,
) -> T: ...


def watch(
	value: object,
	name: str | None = None,
	*,
	threshold: object | None = None,
	show_time: bool = True,
	show_file: bool = True,
	show_lineno: bool = True,
) -> object:
	"""Log without changing behaviour; callables come back wrapped, rest untouched"""

	if not config._g_enabled or config._g_deco_only:
		return value

	frame = _caller_frame()

	if name is None:
		name = _infer_name_from_frame(frame)

	if name and frame is not None:
		_mark_watched(frame, name, threshold=threshold)
		_install_global_trace(frame)

	filename, lineno = _get_location(frame)

	if callable(value) and not inspect.isclass(value):
		wrapped = _log_function(
			value,
			show_time=show_time,
			show_file=show_file,
			show_lineno=show_lineno,
		)

		_emit_named_or_message(
			name,
			f"<func {_path(value)}>",
			frame=frame,
			filename=filename,
			lineno=lineno,
			show_time=show_time,
			show_file=show_file,
			show_lineno=show_lineno,
		)

		return wrapped

	_emit_named_or_message(
		name,
		value,
		frame=frame,
		filename=filename,
		lineno=lineno,
		show_time=show_time,
		show_file=show_file,
		show_lineno=show_lineno,
	)

	return value


# ========================
#     FUNCTION LOGGING
# ========================


# Helpers
def _format_call_signature(name: str, args: tuple[object, ...], kwargs: Mapping[str, object]) -> str:
	arg_parts = [", ".join(_safe_repr(a) for a in args)] if args else []
	kw_parts = [", ".join(f"{k}={_safe_repr(v)}" for k, v in kwargs.items())] if kwargs else []
	joined = ", ".join([p for p in arg_parts + kw_parts if p])
	return f"{name}({joined})"


def _collect_code_objects(func: object) -> set[CodeType]:
	codes: set[CodeType] = set()
	seen: set[int] = set()

	def walk(f: object) -> None:
		if id(f) in seen:
			return
		seen.add(id(f))

		code = getattr(f, "__code__", None)
		if isinstance(code, CodeType):
			codes.add(code)

		# noinspection PyUnnecessaryCast
		wrapped = cast(object, getattr(f, "__wrapped__", None))
		if wrapped is not None:
			walk(wrapped)

		# lru_cache & co. expose no __code__ for settrace to attach to

		# Closures, for stacked decorators
		# noinspection PyUnnecessaryCast
		closure = cast("tuple[CellType, ...] | None", getattr(f, "__closure__", None))
		if closure:
			for cell in closure:
				try:
					obj = cast(object, cell.cell_contents)
				except ValueError:
					continue

				if callable(obj):
					walk(obj)

	walk(func)
	return codes


def _unwrap_callable(func: Callable[..., object]) -> Callable[..., object]:
	unwrapped = cast(object, inspect.unwrap(func))
	return unwrapped if callable(unwrapped) else func


def _callable_display_name(obj: object) -> str:
	"""Best available name for a callable, including ones carrying no __qualname__

	functools.partial objects and instances of a class defining __call__ have
	neither __qualname__ nor __name__, and used to log as an empty name.
	"""
	for attr in ("__qualname__", "__name__"):
		# noinspection PyUnnecessaryCast
		candidate = cast(object, getattr(obj, attr, None))
		if isinstance(candidate, str) and candidate:
			return candidate

	inner = cast(object, getattr(obj, "func", None))
	if inner is not None and callable(inner):
		return f"partial({_callable_display_name(inner)})"

	return type(obj).__qualname__


def _log_function(
	func: Callable[P, T],
	*,
	filepath: str | None = None,
	level: Level = "full",
	filter_set: set[str] | None = None,
	mode: Mode = "full",
	threshold: object | None = None,
	show_time: bool = True,
	show_file: bool = True,
	show_lineno: bool = True,
	show_wrapper_locals: bool = False,
) -> Callable[P, T]:
	"""Wrap a function so sys.settrace reports its calls, locals, returns and raises"""

	target_func = _unwrap_callable(func)

	# noinspection PyUnnecessaryCast
	raw_code = cast(object, getattr(target_func, "__code__", None))
	target_code = raw_code if isinstance(raw_code, CodeType) else None

	is_method_like = bool(target_code and target_code.co_varnames and target_code.co_varnames[0] in {"self", "cls"})

	# Called with self / cls first; a bound method was handed it already
	takes_self = is_method_like and not inspect.ismethod(cast(object, func))

	# noinspection PyUnnecessaryCast
	qualname = cast(object, getattr(target_func, "__qualname__", None))
	if not isinstance(qualname, str) or not qualname:
		qualname = _callable_display_name(func)

	func_path = qualname.replace(".<locals>.", ".")

	allowed_codes: set[CodeType]

	if show_wrapper_locals:
		allowed_codes = _collect_code_objects(func)
	else:
		allowed_codes = {target_code} if target_code is not None else set()

	is_generator = inspect.isgeneratorfunction(target_func)
	is_async = inspect.iscoroutinefunction(target_func) or inspect.isasyncgenfunction(target_func)

	# Its frame suspends: a "return" event may be a yield or an await, not the end
	suspends = is_generator or is_async

	call_counter = 0

	def should_emit(kind: str, name: str) -> bool:
		if level == "call" and kind not in ("call", "return", "raise", "yield"):
			return False

		if level == "state" and kind == "call":
			return False

		if filter_set:
			parts = name.split(".")
			candidates = parts[1:] if len(parts) > 1 else parts

			if not any(part in filter_set for part in candidates):
				return False

		# Educational narrows further after level and filter
		if mode == "educational" and kind == "set":
			var = name.split(".")[-1]

			if var in ("_", "i", "j", "k", "idx", "tmp", "val"):
				return False

		return True

	# With nothing to narrow change tracking need not ask on every line
	emit_gate = should_emit if level != "full" or filter_set or mode != "full" else None

	def _enter_call() -> config.DisplayState:
		"""Make this call's settings the ones every nested emit reads"""

		return config._push_display(mode, show_time, show_file, show_lineno, filepath, emit_gate)

	def _build_tracer(
		display_call_name: str,
		call_signature: str,
		args: tuple[object, ...],
		kwargs: dict[str, object],
		should_emit: Callable[[str, str], bool],
	) -> _CallState:
		tracked: dict[FrameType, str] = {}
		baseline: dict[FrameType, dict[str, object]] = {}
		previous_line: dict[FrameType, int] = {}
		pending_exception: dict[FrameType, object] = {}

		# Plain copies of container locals, to tell when one changed in place
		snapshots: dict[FrameType, dict[str, object]] = {}

		# A nested frame's own (args, signature); the call's would misreport its exit
		nested_calls: dict[FrameType, tuple[tuple[object, ...], str]] = {}

		lambda_counter = 0

		def _remember(frame: FrameType, key: str, value: object) -> None:
			baseline[frame][key] = value

			copy = _snapshot(value)
			if copy is _NO_VALUE:
				_ = snapshots[frame].pop(key, None)
			else:
				snapshots[frame][key] = copy

		def _report_attributes(obj: object, before: _Attributes, prefix: str, filename: str, lineno: int) -> None:
			"""Report the attributes of `obj` that changed since `before`, which follows along"""

			# noinspection PyUnnecessaryCast
			current = cast("dict[str, object]", vars(obj))

			for attr, now in list(current.items()):
				if attr.startswith("_"):
					continue

				was = before.get(attr, _NO_VALUE)

				kind: Kind
				if was is _NO_VALUE:
					kind = "set"
				elif _differs(was, now):
					kind = "change"
				else:
					continue

				name = f"{prefix}.{attr}"

				if not _passes_threshold(was, now, _resolve_threshold_for_name(name, threshold)):
					continue

				if should_emit(kind, name):
					_emit(
						kind,
						name,
						now,
						filename=filename,
						lineno=lineno,
						filepath=filepath,
						show_time=show_time,
						show_file=show_file,
						show_lineno=show_lineno,
					)

				before[attr] = _unwrap_value(now)

		def _sample_locals(frame: FrameType, frame_name: str, lineno: int) -> None:
			code = frame.f_code
			filename = code.co_filename
			known = baseline[frame]
			copies = snapshots[frame]

			# noinspection PyUnnecessaryCast
			locals_view = cast("dict[str, object]", frame.f_locals)

			# A comprehension's loop variable is not one of the function's own
			in_flight = _comprehension_variables(filename, lineno)

			value: object

			for key, value in list(locals_view.items()):
				if key == "_" or key in in_flight:
					continue

				if key in {"self", "cls"}:
					known[key] = value
					continue

				if is_method_like and key in code.co_varnames[: code.co_argcount]:
					known[key] = value
					continue

				old = known.get(key, _NO_VALUE)

				# Already reported by an explicit log() / watch()
				if _was_just_emitted(code, key, lineno):
					_remember(frame, key, value)
					continue

				# Swapped for a logging copy only when this statement just built it:
				# anything else may be referenced elsewhere, and the copy would split them
				if old is not value and type(value) in _CONTAINERS:
					depth = _fresh_binding(filename, lineno, key)

					if depth:
						wrapped: object = _wrap_value(value, name=f"{frame_name}.{key}", deep=depth > 1)

						try:
							locals_view[key] = wrapped
						except (TypeError, ValueError):
							pass
						else:
							value = wrapped  # noqa: PLW2901 -- the logging copy stands in from here on

				if callable(value):
					continue

				previous = old
				current = value
				in_place = old is value

				if in_place:
					if isinstance(value, _BaseLogged):
						# It reports its own changes; C code like heapq goes around them
						if _line_may_mutate(filename, lineno, key):
							value._logeye_resync(filename, lineno, key)
						continue

					# Same object; only a change made in place shows, against the copy
					copy = copies.get(key, _NO_VALUE)

					if copy is _NO_VALUE or not _line_may_mutate(filename, lineno, key):
						continue

					if isinstance(copy, _Attributes):
						_report_attributes(value, copy, f"{frame_name}.{key}", filename, lineno)
						continue

					previous = copy
					current = _comparable(value)

				name = f"{frame_name}.{key}"

				kind: Kind

				if previous is _NO_VALUE:
					kind = "set"
				elif _differs(previous, current):
					kind = "change"
				else:
					continue

				threshold_spec = _resolve_threshold_for_name(name, threshold)
				if threshold_spec is None:
					threshold_spec = _resolve_threshold_for_name(key, _watch_threshold(code, key))

				if not _passes_threshold(previous, current, threshold_spec):
					continue

				if should_emit(kind, name):
					shown: object = value

					# Changed in place: written as the call on that line that did it
					if in_place:
						observed = _observed_change(_observed_call(filename, lineno, key), previous, value)
						if observed is not None:
							shown = observed

					_emit(
						kind,
						name,
						shown,
						filename=filename,
						lineno=lineno,
						filepath=filepath,
						show_time=show_time,
						show_file=show_file,
						show_lineno=show_lineno,
					)

					_remember(frame, key, value)

		def _register(frame: FrameType, name: str) -> None:
			# Resuming a generator re-fires "call"; keep the baseline
			if frame in tracked:
				return

			tracked[frame] = name
			baseline[frame] = {}
			snapshots[frame] = {}
			previous_line[frame] = frame.f_lineno

		def _release(frame: FrameType) -> None:
			_ = tracked.pop(frame, None)
			_ = baseline.pop(frame, None)
			_ = snapshots.pop(frame, None)
			_ = nested_calls.pop(frame, None)
			_ = previous_line.pop(frame, None)
			_ = pending_exception.pop(frame, None)

		def _trace(frame: FrameType, event: str, arg: object) -> TraceFunction | None:
			nonlocal lambda_counter

			code = frame.f_code

			if event == "call":
				filename = code.co_filename

				if _is_library_file(filename):
					return None

				if code in allowed_codes:
					_register(frame, display_call_name)
					state.traced = True
					return tracer

				parent = frame.f_back
				parent_name = tracked.get(parent) if parent is not None else None

				if parent_name is None:
					return None

				# Stop at the edge of user code, the stdlib is pages of noise
				if _is_external_code(filename):
					return None

				# An awaited coroutine suspends and resumes on its own; @log traces it whole
				if code.co_flags & _ASYNC_CODE:
					return None

				nested_name = code.co_name

				if nested_name == "<lambda>":
					lambda_counter += 1
					nested_name = f"lambda#{lambda_counter}"
					nested_full_name = f"{display_call_name}.{nested_name}"
				else:
					if nested_name == getattr(target_func, "__name__", None):
						return None

					if nested_name.startswith("__"):
						return None

					if nested_name in _SKIPPED_NESTED_NAMES:
						return None

					nested_full_name = f"{parent_name}.{nested_name}"

				_register(frame, nested_full_name)

				lineno = frame.f_lineno
				# noinspection PyUnnecessaryCast
				locals_snapshot = cast("dict[str, object]", frame.f_locals)

				defaults = {
					name: locals_snapshot[name]
					for name in code.co_varnames[: code.co_argcount]
					if name in locals_snapshot and name not in {"self", "cls"}
				}

				passed = tuple(_unwrap_value(v) for v in defaults.values())
				nested_calls[frame] = (
					passed,
					_format_call_signature(nested_full_name, passed, {}),
				)

				if should_emit("call", nested_full_name):
					_emit(
						"call",
						nested_full_name,
						{"args": (), "kwargs": {}},
						filename=filename,
						lineno=lineno,
						filepath=filepath,
						show_time=show_time,
						show_file=show_file,
						show_lineno=show_lineno,
					)

				_emit(
					"set",
					nested_full_name,
					{
						"type": "function",
						"path": nested_full_name,
						"defaults": defaults,
					},
					filename=filename,
					lineno=lineno,
					filepath=filepath,
					show_time=show_time,
					show_file=show_file,
					show_lineno=show_lineno,
				)

				for key, value in locals_snapshot.items():
					if key in {"self", "cls"} or key not in code.co_varnames:
						continue

					name = f"{nested_full_name}.{key}"
					if should_emit("set", name):
						_emit(
							"set",
							name,
							value,
							filename=filename,
							lineno=lineno,
							filepath=filepath,
							show_time=show_time,
							show_file=show_file,
							show_lineno=show_lineno,
						)
						_mark_emitted(frame, key)
						_remember(frame, key, value)

				return tracer

			frame_name = tracked.get(frame)
			if frame_name is None:
				return None

			if event == "line":
				# More lines in this frame means it was caught here
				_ = pending_exception.pop(frame, None)

				_sample_locals(frame, frame_name, previous_line.get(frame, frame.f_lineno))
				previous_line[frame] = frame.f_lineno
				return tracer

			if event == "exception":
				pending_exception[frame] = arg
				return tracer

			if event == "return":
				lineno = previous_line.get(frame, frame.f_lineno)

				# The final statement's values are only visible here
				_sample_locals(frame, frame_name, lineno)

				raised = pending_exception.pop(frame, None)

				# A nested frame reports its own arguments, not the traced call's
				frame_args, frame_kwargs, frame_signature = args, kwargs, call_signature
				if frame in nested_calls:
					frame_args, frame_signature = nested_calls[frame]
					frame_kwargs = {}

				if raised is not None and arg is None:
					if should_emit("raise", frame_name):
						# An "exception" event's arg is (type, value, traceback)
						exc_info = cast("tuple[type[BaseException], BaseException, object]", raised)
						exc_type, exc_value = exc_info[0], exc_info[1]

						_emit(
							"raise",
							frame_name,
							{
								"exception": exc_value,
								"exception_type": getattr(exc_type, "__name__", str(exc_type)),
								"args": frame_args,
								"kwargs": frame_kwargs,
								"call_signature": frame_signature,
							},
							filename=frame.f_code.co_filename,
							lineno=lineno,
							filepath=filepath,
							show_time=show_time,
							show_file=show_file,
							show_lineno=show_lineno,
						)
				elif suspends and code is target_code:
					# Only the wrapper knows whether this was a yield, an await or the end
					state.exit_line = lineno
					return tracer
				elif should_emit("return", frame_name):
					payload: dict[str, object] = {
						"value": arg,
						"args": frame_args,
						"kwargs": frame_kwargs,
						"call_signature": frame_signature,
					}

					_emit(
						"return",
						frame_name,
						payload,
						filename=frame.f_code.co_filename,
						lineno=lineno,
						filepath=filepath,
						show_time=show_time,
						show_file=show_file,
						show_lineno=show_lineno,
					)

				_release(frame)

			return tracer

		# Under coverage the body runs where the coverage tool can see it
		tracer = _measurable(_trace)

		state = _CallState(
			tracer=tracer,
			name=display_call_name,
			signature=call_signature,
			should_emit=should_emit,
			args=args,
			kwargs=kwargs,
		)

		return state

	def _prepare(args: tuple[object, ...], kwargs: dict[str, object], skip_external: bool = False) -> _CallState:
		"""Per-call setup: naming, the call record and the tracer"""

		nonlocal call_counter

		call_counter += 1
		call_id = call_counter
		call_name = f"{func_path}{'' if call_id == 1 else f'#{call_id}'}"

		call_frame = _caller_frame(skip_external)
		call_filename, call_lineno = _get_location(call_frame)

		bound_name = None
		if takes_self and args:
			bound_name = getattr(args[0], "_logeye_name", None)

		shown_args = args[1:] if takes_self else args

		# Frozen as passed; by the (return) line the body may have changed them in place
		passed_args = tuple(_unwrap_value(a) for a in shown_args)
		passed_kwargs = {k: _unwrap_value(v) for k, v in kwargs.items()}

		display_call_name = call_name
		if bound_name:
			method_name = func_path.split(".")[-1]
			display_call_name = f"{bound_name}.{method_name}"

		call_signature = _format_call_signature(display_call_name, shown_args, kwargs)

		if should_emit("call", display_call_name):
			target = _get_assignment_target_for_call(call_frame)

			_emit(
				"call",
				display_call_name,
				{"target": target, "args": shown_args, "kwargs": kwargs},
				filename=call_filename,
				lineno=call_lineno,
				filepath=filepath,
				show_time=show_time,
				show_file=show_file,
				show_lineno=show_lineno,
			)

		state = _build_tracer(display_call_name, call_signature, passed_args, passed_kwargs, should_emit)

		state.call_filename = call_filename
		state.call_lineno = call_lineno

		return state

	def _emit_untraced_exit(state: _CallState, kind: Kind, payload: dict[str, object]) -> None:
		"""Report an exit sys.settrace never saw"""

		if state.traced or not state.should_emit(kind, state.name):
			return

		payload["args"] = state.args
		payload["kwargs"] = state.kwargs
		payload["call_signature"] = state.signature

		# Its own display state: an awaited coroutine is no longer inside the call
		previous = _enter_call()
		try:
			_emit(
				kind,
				state.name,
				payload,
				filename=state.call_filename,
				lineno=state.call_lineno,
				filepath=filepath,
				show_time=show_time,
				show_file=show_file,
				show_lineno=show_lineno,
			)
		finally:
			config._pop_display(previous)

	def _raised(caught: BaseException) -> dict[str, object]:
		return {"exception": caught, "exception_type": type(caught).__name__}

	def _emit_exit(state: _CallState, kind: Kind, value: object) -> None:
		"""Report a yield, or the end, of a body that suspends, from where it stopped"""

		if not state.should_emit(kind, state.name):
			return

		payload: dict[str, object] = {
			"value": value,
			"args": state.args,
			"kwargs": state.kwargs,
			"call_signature": state.signature,
		}

		previous = _enter_call()
		try:
			_emit(
				kind,
				state.name,
				payload,
				filename=target_code.co_filename if target_code else None,
				lineno=state.exit_line,
				filepath=filepath,
				show_time=show_time,
				show_file=show_file,
				show_lineno=show_lineno,
			)
		finally:
			config._pop_display(previous)

	def _resume(state: _CallState, step: Callable[[], object]) -> object:
		"""
		Run one step of a suspended body with its tracer installed, and only that step
		The body runs on next() / send() / an event loop's schedule, long after the call
		returned, and between steps other code keeps whatever tracing it had
		"""

		previous = _enter_call()
		old_trace = sys.gettrace()
		sys.settrace(state.tracer)

		try:
			return step()
		finally:
			sys.settrace(old_trace)
			config._pop_display(previous)

	def _drive(state: _CallState, awaitable: Awaitable[object]) -> Generator[object, object, object]:
		"""
		Await `awaitable` one step at a time, traced only while its body runs
		Whenever it suspends, the event loop's other tasks run without this call's tracer
		"""

		steps = awaitable.__await__()
		step: Callable[[], object] = functools.partial(steps.send, None)

		while True:
			try:
				suspended_on = _resume(state, step)
			except StopIteration as stop:
				return cast(object, stop.value)

			try:
				sent = yield suspended_on
			except GeneratorExit:
				steps.close()
				raise
			except BaseException as caught:
				step = functools.partial(steps.throw, caught)
			else:
				step = functools.partial(steps.send, sent)

	if target_code is None:
		# C callables don't have a Python frame; tracer can't see the exit
		@functools.wraps(func)
		def native_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
			if not config._g_enabled:
				return func(*args, **kwargs)

			previous = _enter_call()
			try:
				state = _prepare(args, kwargs)

				try:
					result = func(*args, **kwargs)
				except BaseException as caught:
					_emit_untraced_exit(state, "raise", _raised(caught))
					raise

				_emit_untraced_exit(state, "return", {"value": result})
				return result
			finally:
				config._pop_display(previous)

		return native_wrapper

	if inspect.iscoroutinefunction(target_func):
		# noinspection PyUnnecessaryCast
		coroutine_func = cast("Callable[..., Awaitable[object]]", func)

		# async def, so inspect.iscoroutinefunction() and every framework asking it agree
		@functools.wraps(func)
		async def coroutine_wrapper(*args: object, **kwargs: object) -> object:
			if not config._g_enabled:
				return await coroutine_func(*args, **kwargs)

			previous = _enter_call()
			try:
				# Run by an event loop, the frame below is asyncio's
				state = _prepare(args, kwargs, skip_external=True)
			finally:
				config._pop_display(previous)

			try:
				result = await _Driven(_drive(state, coroutine_func(*args, **kwargs)))
			except BaseException as caught:
				# Before the body ran (bad arguments); after it, the tracer reported it
				_emit_untraced_exit(state, "raise", _raised(caught))
				raise

			_emit_exit(state, "return", result)
			return result

		# noinspection PyUnnecessaryCast
		return cast("Callable[P, T]", coroutine_wrapper)

	if inspect.isasyncgenfunction(target_func):
		# noinspection PyUnnecessaryCast
		agen_func = cast("Callable[..., AsyncGenerator[object, object]]", func)

		# async def with yield, so it is an async generator function to anything that asks
		@functools.wraps(func)
		async def async_generator_wrapper(*args: object, **kwargs: object) -> AsyncGenerator[object, object]:
			generator = agen_func(*args, **kwargs)
			state: _CallState | None = None

			if config._g_enabled:
				previous = _enter_call()
				try:
					state = _prepare(args, kwargs, skip_external=True)
				finally:
					config._pop_display(previous)

			def run(awaitable: Awaitable[object]) -> Awaitable[object]:
				return awaitable if state is None else _Driven(_drive(state, awaitable))

			# What to run next: asend() the consumer's value, or athrow() its exception
			step: Callable[[], Awaitable[object]] = functools.partial(generator.asend, None)

			while True:
				try:
					item = await run(step())
				except StopAsyncIteration:
					if state is not None:
						_emit_exit(state, "return", None)
					return

				if state is not None:
					_emit_exit(state, "yield", item)

				try:
					sent = yield item
				except GeneratorExit:
					_ = await run(generator.aclose())
					raise
				except BaseException as caught:
					step = functools.partial(generator.athrow, caught)
				else:
					step = functools.partial(generator.asend, sent)

		# noinspection PyUnnecessaryCast
		return cast("Callable[P, T]", async_generator_wrapper)

	if is_generator:
		# noinspection PyUnnecessaryCast
		gen_func = cast("Callable[..., Generator[object, object, object]]", func)

		@functools.wraps(func)
		def generator_wrapper(*args: object, **kwargs: object) -> Generator[object, object, object]:
			if not config._g_enabled:
				return (yield from gen_func(*args, **kwargs))

			previous = _enter_call()
			try:
				state = _prepare(args, kwargs)
			finally:
				config._pop_display(previous)

			generator = gen_func(*args, **kwargs)

			# What to run next: send() the consumer's value, or throw() its exception
			step: Callable[[], object] = functools.partial(generator.send, None)

			while True:
				try:
					item = _resume(state, step)
				except StopIteration as stop:
					returned = cast(object, stop.value)
					_emit_exit(state, "return", returned)

					# `yield from` hands this on to whoever delegated
					return returned

				_emit_exit(state, "yield", item)

				try:
					sent = yield item
				except GeneratorExit:
					_ = generator.close()
					raise
				except BaseException as caught:
					step = functools.partial(generator.throw, caught)
				else:
					step = functools.partial(generator.send, sent)

		# noinspection PyUnnecessaryCast
		return cast("Callable[P, T]", generator_wrapper)

	@functools.wraps(func)
	def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
		if not config._g_enabled:
			return func(*args, **kwargs)

		previous = _enter_call()

		try:
			state = _prepare(args, kwargs)

			old_trace = sys.gettrace()
			sys.settrace(state.tracer)

			try:
				result = func(*args, **kwargs)
			except BaseException as caught:
				sys.settrace(old_trace)

				# A C decorator in between may have raised before the body ran
				_emit_untraced_exit(state, "raise", _raised(caught))
				raise
			finally:
				sys.settrace(old_trace)

			# Nothing was traced when a C decorator answered on its own
			_emit_untraced_exit(state, "return", {"value": result})
			return result
		finally:
			config._pop_display(previous)

	return wrapper


# ========================
# OBJECT / MESSAGE LOGGING
# ========================


def _log_object(
	obj: T | Mapping[K, V],
	name: str | None = None,
	*,
	show_time: bool = True,
	show_file: bool = True,
	show_lineno: bool = True,
) -> T | LoggedObject[T | Mapping[K, V]] | Mapping[K, V]:
	if not config._g_enabled or config._g_deco_only:
		return obj

	frame = _caller_frame()

	try:
		if name is None:
			name = _get_assignment_target_for_call(frame)

		wrapped = LoggedObject(obj, name=name or "set")

		filename, lineno = _get_location(frame)

		value: dict[object, object]

		if isinstance(obj, Mapping):
			# noinspection PyUnnecessaryCast
			value = dict(cast("Mapping[object, object]", obj))
		else:
			value = cast("dict[object, object]", cast(object, vars(obj)))

		_emit_named_or_message(
			name,
			value,
			frame=frame,
			filename=filename,
			lineno=lineno,
			show_time=show_time,
			show_file=show_file,
			show_lineno=show_lineno,
		)
	finally:
		del frame

	return wrapped


def _log_message(
	text: str,
	*args: object,
	show_time: bool = True,
	show_file: bool = True,
	show_lineno: bool = True,
	**kwargs: object,
) -> str:
	frame = _caller_frame()

	try:
		# The template is expanded once; a value it pulls in is never expanded again
		rendered = _format_message(text, *args, **kwargs) if args or kwargs else _expand_template(text)

		if not config._g_enabled or config._g_deco_only:
			return rendered

		name = _get_assignment_target_for_call(frame)

		filename, lineno = _get_location(frame)

		if name and frame is not None:
			_mark_watched(frame, name)
			_install_global_trace(frame)

			_emit(
				"set",
				name,
				rendered,
				filename=filename,
				lineno=lineno,
				show_time=show_time,
				show_file=show_file,
				show_lineno=show_lineno,
			)

			_mark_emitted(frame, name)
		else:
			_emit(
				"message",
				"message",
				rendered,
				filename=filename,
				lineno=lineno,
				show_time=show_time,
				show_file=show_file,
				show_lineno=show_lineno,
			)

	finally:
		del frame

	return rendered


# =====================
#   PUBLIC ENTRYPOINT
# =====================


@overload
def _dispatch_log(
	obj: str,
	*args: object,
	file: str | None = ...,
	filepath: str | None = ...,
	level: Level = ...,
	filter: Iterable[str] | None = ...,
	mode: Mode | None = ...,
	threshold: object | None = None,
	show_time: bool | None = ...,
	show_file: bool | None = ...,
	show_lineno: bool | None = ...,
	show_wrapper_locals: bool | None = None,
	**kwargs: object,
) -> str: ...


@overload
def _dispatch_log(
	*,
	file: str | None = ...,
	filepath: str | None = ...,
	level: Level = ...,
	filter: Iterable[str] | None = ...,
	mode: Mode | None = ...,
	threshold: object | None = None,
	show_time: bool | None = ...,
	show_file: bool | None = ...,
	show_lineno: bool | None = ...,
	show_wrapper_locals: bool | None = None,
) -> Callable[[Callable[P, T]], Callable[P, T]]: ...


@overload
def _dispatch_log(
	obj: Mapping[K, V],
	*args: object,
	file: str | None = ...,
	filepath: str | None = ...,
	level: Level = ...,
	filter: Iterable[str] | None = ...,
	mode: Mode | None = ...,
	threshold: object | None = None,
	show_time: bool | None = ...,
	show_file: bool | None = ...,
	show_lineno: bool | None = ...,
	show_wrapper_locals: bool | None = None,
	**kwargs: object,
) -> LoggedDict[K, V]: ...


@overload
def _dispatch_log(
	obj: Callable[P, T],
	*args: object,
	file: str | None = ...,
	filepath: str | None = ...,
	level: Level = ...,
	filter: Iterable[str] | None = ...,
	mode: Mode | None = ...,
	threshold: object | None = None,
	show_time: bool | None = ...,
	show_file: bool | None = ...,
	show_lineno: bool | None = ...,
	show_wrapper_locals: bool | None = None,
	**kwargs: object,
) -> Callable[P, T]: ...


@overload
def _dispatch_log(
	obj: T,
	*args: object,
	file: str | None = ...,
	filepath: str | None = ...,
	level: Level = ...,
	filter: Iterable[str] | None = ...,
	mode: Mode | None = ...,
	threshold: object | None = None,
	show_time: bool | None = ...,
	show_file: bool | None = ...,
	show_lineno: bool | None = ...,
	show_wrapper_locals: bool | None = None,
	**kwargs: object,
) -> T: ...


def _dispatch_log(
	obj: Callable[P, T] | Mapping[K, V] | object = _NO_VALUE,
	*args: object,
	file: str | None = None,
	filepath: str | None = None,
	level: Level = "full",
	filter: Iterable[str] | None = None,
	mode: Mode | None = None,
	threshold: object | None = None,
	show_time: bool | None = None,
	show_file: bool | None = None,
	show_lineno: bool | None = None,
	show_wrapper_locals: bool | None = None,
	**kwargs: object,
) -> object:
	"""
	Dispatch on input type
	class -> patch __init__ | function -> trace | str -> message mapping/object -> LoggedObject | other -> value logging
	"""

	if show_wrapper_locals is None:
		show_wrapper_locals = False

	mode = config._mode() if mode is None else config._normalize_mode(mode)

	filter_set = set(filter) if filter else None
	deco_path = _resolve_filepath(file=file, filepath=filepath)

	if show_time is None:
		show_time = config._show_time()

	if show_file is None:
		show_file = config._show_file()

	if show_lineno is None:
		show_lineno = config._show_lineno()

	if mode == "educational":
		show_file = False
		show_lineno = False

	if isinstance(obj, (staticmethod, classmethod)):
		# Wrap the function inside; a plain wrapper in a class body would be handed self
		# noinspection PyUnnecessaryCast
		descriptor = cast("staticmethod[..., object] | classmethod[object, ..., object]", obj)

		return type(descriptor)(
			_log_function(
				descriptor.__func__,
				filepath=deco_path,
				level=level,
				filter_set=filter_set,
				mode=mode,
				threshold=threshold,
				show_time=show_time,
				show_file=show_file,
				show_lineno=show_lineno,
				show_wrapper_locals=show_wrapper_locals,
			)
		)

	if inspect.isclass(obj):
		return _log_class(
			obj,
			filepath=deco_path,
			level=level,
			mode=mode,
			show_time=show_time,
			show_file=show_file,
			show_lineno=show_lineno,
		)

	if callable(obj):
		return _log_function(
			obj,
			filepath=deco_path,
			level=level,
			filter_set=filter_set,
			mode=mode,
			threshold=threshold,
			show_time=show_time,
			show_file=show_file,
			show_lineno=show_lineno,
			show_wrapper_locals=show_wrapper_locals,
		)

	if isinstance(obj, str):
		return _log_message(
			obj,
			*args,
			show_time=show_time,
			show_file=show_file,
			show_lineno=show_lineno,
			**kwargs,
		)

	# Do NOT wrap class instances
	if isinstance(obj, Mapping):
		return _log_object(
			cast("Mapping[object, object]", obj),
			show_time=show_time,
			show_file=show_file,
			show_lineno=show_lineno,
		)

	# An instance of a @log class already reported its own construction
	if getattr(type(obj).__init__, "_logeye_patched", False):
		return obj

	if isinstance(obj, list):
		frame = _caller_frame()

		try:
			name = _get_assignment_target_for_call(frame)
			filename, lineno = _get_location(frame)

			if name and frame is not None:
				_mark_watched(frame, name, threshold=threshold)
				_install_global_trace(frame)

			_emit_named_or_message(
				name,
				cast(object, obj),
				frame=frame,
				filename=filename,
				lineno=lineno,
				show_time=show_time,
				show_file=show_file,
				show_lineno=show_lineno,
			)

			# noinspection PyUnnecessaryCast
			return _wrap_value(cast("list[object]", obj), name=name or "set")
		finally:
			del frame

	return watch(
		obj,
		threshold=threshold,
		show_time=show_time,
		show_file=show_file,
		show_lineno=show_lineno,
	)


_dispatch_untyped = cast("Callable[..., object]", _dispatch_log)


class _BoundLog:
	"""
	A log(...) call that carried options but no value yet
	Each configuration gets its own object, so an unrelated call cannot consume it
	"""

	__slots__: tuple[str, ...] = ("_options",)

	_options: dict[str, object]

	def __init__(self, options: dict[str, object]) -> None:
		self._options = options

	def __call__(
		self,
		obj: Callable[P, T] | Mapping[K, V] | object = _NO_VALUE,
		*args: object,
		**kwargs: object,
	) -> object:
		merged = {**self._options, **kwargs}

		if obj is _NO_VALUE:
			return _BoundLog(merged)

		return _dispatch_untyped(obj, *args, **merged)

	def __ror__(self, other: object) -> object:
		return _dispatch_untyped(other, **self._options)


class _LogAPI:
	def __call__(
		self,
		obj: Callable[P, T] | Mapping[K, V] | object = _NO_VALUE,
		*args: object,
		file: str | None = None,
		filepath: str | None = None,
		level: Level = "full",
		filter: Iterable[str] | None = None,
		mode: Mode | None = None,
		threshold: object | None = None,
		show_time: bool | None = None,
		show_file: bool | None = None,
		show_lineno: bool | None = None,
		show_wrapper_locals: bool | None = None,
		**kwargs: object,
	) -> object:
		options: dict[str, object] = {
			"file": file,
			"filepath": filepath,
			"level": level,
			"filter": filter,
			"mode": mode,
			"threshold": threshold,
			"show_time": show_time,
			"show_file": show_file,
			"show_lineno": show_lineno,
			"show_wrapper_locals": show_wrapper_locals,
			**kwargs,
		}

		if obj is _NO_VALUE:
			return _BoundLog(options)

		return _dispatch_untyped(obj, *args, **options)

	def __ror__(self, other: object) -> object:
		return _log_pipe_value(other)


def _log_pipe_value(other: object) -> object:
	frame = _caller_frame()

	try:
		name = _infer_name_from_frame(frame)
		filename, lineno = _get_location(frame)

		if name and frame is not None:
			_mark_watched(frame, name)
			_install_global_trace(frame)

			_emit("set", name, other, filename=filename, lineno=lineno)

			_mark_emitted(frame, name)
		else:
			_emit("message", "message", other, filename=filename, lineno=lineno)
	finally:
		del frame

	return other


__all__ = [
	"Kind",
	"Level",
	"_BoundLog",
	"_LogAPI",
	"_dispatch_log",
	"_log_class",
	"_log_function",
	"_log_message",
	"_log_object",
	"_log_pipe_value",
	"watch",
]
