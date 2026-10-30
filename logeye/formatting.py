from __future__ import annotations

import os
import inspect

from . import config
from collections.abc import Iterable, Mapping, Sequence
from typing import TYPE_CHECKING, Callable, Optional, Tuple, cast
from .introspection.frames import _relative_path

if TYPE_CHECKING:
	from typing_extensions import TypeAlias

	from .core import Kind

# Returns the line to write, or None to drop the event
Formatter: TypeAlias = Callable[..., Optional[str]]

# (positional argument count, accepts display flags)
FormatterShape: TypeAlias = Tuple[int, bool]


def _payload_of(value: object) -> dict[str, object] | None:
	"""View an emitted value as its payload dict; logeye builds them, str-keyed"""

	if isinstance(value, dict):
		# noinspection PyUnnecessaryCast
		return cast("dict[str, object]", value)

	return None


def _payload_args(payload: Mapping[str, object]) -> tuple[object, ...]:
	"""The `args` entry of a payload, as a tuple"""

	args = payload.get("args")
	return tuple(cast("Iterable[object]", args)) if args else ()


def _payload_kwargs(payload: Mapping[str, object]) -> dict[str, object]:
	"""The `kwargs` entry of a payload, as a dict"""

	kwargs = payload.get("kwargs")
	return dict(cast("Mapping[str, object]", kwargs)) if kwargs else {}


def _payload_defaults(payload: Mapping[str, object]) -> dict[str, object]:
	"""The `defaults` entry of a nested-definition payload, as a dict"""

	defaults = payload.get("defaults")
	return dict(cast("Mapping[str, object]", defaults)) if defaults else {}


def _last_name(name: str) -> str:
	return name.split(".")[-1]


def _is_simple_value(value: object) -> bool:
	return isinstance(value, (str, int, float, bool, type(None)))


def _display_name(name: str) -> str:
	parts = [p for p in name.split(".") if not p.startswith("test_")]
	return ".".join(parts) if parts else name


def _safe_repr(value: object) -> str:
	"""repr() that cannot take the logged program down with it"""

	try:
		return repr(value)
	except Exception as exc:
		return f"<{type(value).__name__} object; repr() raised {type(exc).__name__}>"


def _pretty_arg(a: object) -> str:
	if hasattr(a, "__class__") and hasattr(a, "__dict__"):
		return a.__class__.__name__

	return repr(a)


def _path(obj: object) -> str:
	"""Readable name/path for a callable or object"""

	qualname = getattr(obj, "__qualname__", None)
	if isinstance(qualname, str):
		return qualname.replace(".<locals>.", ".")

	name = getattr(obj, "__name__", None)
	return name if isinstance(name, str) else str(obj)


def _format_op_arguments(op: str, payload: dict[str, object]) -> str:
	"""Render a mutation's arguments so the log reads like the call"""

	val = payload.get("value")

	if op == "sort":
		args = _payload_args(payload)
		kwargs = _payload_kwargs(payload)

		return ", ".join(
			[
				*(repr(a) for a in args),
				*(f"{k}={v!r}" for k, v in kwargs.items()),
			]
		)

	if op == "insert":
		return f"{payload.get('index')!r}, {val!r}"

	if op == "setdefault":
		return f"{payload.get('key')!r}, {val!r}"

	if op == "delitem":
		return repr(payload.get("key"))

	if op == "imul":
		return repr(payload.get("factor"))

	if op == "pop":
		if "key" in payload:
			return repr(payload.get("key"))

		# pop(-1) is just pop()
		index = payload.get("index")
		return "" if index is None or index == -1 else repr(index)

	if op in ("clear", "reverse", "popitem"):
		return ""

	return repr(val) if "value" in payload else ""


def _payload_items(payload: Mapping[str, object], key: str) -> list[object]:
	items = payload.get(key)
	# noinspection PyUnnecessaryCast
	return list(cast("Iterable[object]", items)) if items else []


def _format_observed(name: str, payload: Mapping[str, object], prefix: str, kind_prefix: str) -> str:
	"""A change noticed only afterwards, written as the call on its line that made it"""

	op = str(payload.get("op"))
	added = _payload_items(payload, "added")
	removed = _payload_items(payload, "removed")
	arguments = payload.get("arguments")

	# The one thing that went in is the argument; anything else is not known for sure
	shown = ""
	if arguments == 1 and len(added) == 1:
		shown = repr(added[0])
	elif arguments:
		shown = "..."

	if payload.get("function"):
		call = f"{op}({', '.join(part for part in (name, shown) if part)})"
	else:
		call = f"{name}.{op}({shown})"

	state = payload.get("state")

	if len(removed) == 1:
		return f"{prefix}{kind_prefix}{call} -> {removed[0]!r} | {state!r}"

	return f"{prefix}{kind_prefix}{call} -> {state!r}"


def _format_change_payload(
	name: str,
	payload: dict[str, object],
	prefix: str,
	*,
	include_kind: bool = True,
) -> str | None:
	op = payload.get("op")
	val = payload.get("value")
	state = payload.get("state")

	kind_prefix = "(change) " if include_kind else ""

	if payload.get("observed"):
		return _format_observed(name, payload, prefix, kind_prefix)

	if op in ("setattr", "setitem"):
		if _is_simple_value(val):
			# More detail here would just be noise
			return f"{prefix}{kind_prefix}{name} = {val!r}"

		return f"{prefix}{kind_prefix}{name} = {val!r} -> {state}"

	if not isinstance(op, str):
		return None

	# Reads as "what was called -> what it produced"
	call = f"{name}.{op}({_format_op_arguments(op, payload)})"

	if op in ("pop", "popitem"):
		return f"{prefix}{kind_prefix}{call} -> {val!r} | {state!r}"

	return f"{prefix}{kind_prefix}{call} -> {state!r}"


def _format_call_payload(args: tuple[object, ...], kwargs: dict[str, object]) -> str:
	parts: list[str] = []

	if args:
		parts.append(f"args=({', '.join(repr(a) for a in args)})")

	if kwargs:
		parts.append(f"kwargs={kwargs!r}")

	return " | ".join(parts)


def _format_call_line(prefix: str, kind: str, func_name: str, payload_str: str, tail: str) -> str:
	"""Join a call line, skipping the payload gap when there are no arguments"""
	head = f"{prefix}({kind}) {func_name}"

	if payload_str:
		head += f" {payload_str}"

	return f"{head} {tail}"


def _default_formatter(
	elapsed: float,
	kind: Kind,
	name: str,
	value: object,
	filename: str | None,
	lineno: int | None,
	*,
	show_time: bool = True,
	show_file: bool = True,
	show_lineno: bool = True,
) -> str | None:
	parts: list[str] = []

	payload = _payload_of(value)

	is_edu_mode = config._mode() == "educational"

	if is_edu_mode:
		show_file = False
		show_lineno = False

	stamp = f"{elapsed:0.3f}s"
	time_prefix = f"[{stamp}] " if show_time else ""

	location = ""

	if show_file and filename:
		location += _format_path(filename)

	if show_lineno and lineno is not None:
		if location:
			location += f":{lineno}"
		else:
			location += str(lineno)

	if location:
		parts.append(location)

	location_prefix = " ".join(parts)
	if location_prefix:
		location_prefix += " "

	prefix = f"{time_prefix}{location_prefix}"

	if is_edu_mode:
		if kind in ("set", "change"):
			is_private = payload is not None and payload.get("type") == "private"

			if payload is not None and "op" in payload:
				op = payload["op"]
				val = payload.get("value")
				state = payload.get("state")

				short_name = _last_name(name)

				if payload.get("observed"):
					added = _payload_items(payload, "added")
					removed = _payload_items(payload, "removed")
					heap = str(op).startswith("heap")

					if len(added) == 1 and not removed:
						verb = "Pushed" if heap else "Added"
						where = "onto" if heap else "to"
						return f"{prefix}{verb} {added[0]} {where} {short_name}"

					if len(removed) == 1 and not added:
						return f"{prefix}Popped {removed[0]} from {short_name}"

					return _format_observed(_display_name(name), payload, prefix, "")

				if op == "append":
					return f"{prefix}Added {val} to the end of {short_name}"

				if op == "extend":
					added: Sequence[object] = cast("Sequence[object]", val) if val else ()

					if not added:
						return None

					if len(added) == 1:
						return f"{prefix}Added {added[0]} to {short_name}"

					return f"{prefix}Added {added} to {short_name}"

				if op == "setitem":
					return f"{prefix}Set {_display_name(name)} = {val}"

				if op == "pop":
					return f"{prefix}Popped {val} from {short_name}"

				if op == "add":
					return f"{prefix}Added {val} to {short_name}"

				if op == "remove":
					return f"{prefix}Removed {val} from {short_name}"

				if op == "sort":
					return f"{prefix}Sorted {short_name} -> {state}"

				if op == "insert":
					idx = payload.get("index")
					return f"{prefix}Inserted {val} at index {idx} in {short_name}"

				# setattr, update, clear, ...: no raw payload dict
				formatted = _format_change_payload(_display_name(name), payload, prefix, include_kind=False)
				if formatted is not None:
					return formatted

			if kind == "set" and payload is not None and payload.get("type") == "function":
				defaults = _payload_defaults(payload)
				short_name = _display_name(name)

				if defaults:
					rendered_defaults = ", ".join(f"{k}={v!r}" for k, v in defaults.items())
					return f"{prefix}Defined {short_name}({rendered_defaults})"

				return f"{prefix}Defined {short_name}()"

			actual = payload["value"] if is_private and payload is not None else value
			prefix_priv = "<priv> " if is_private else ""

			if kind == "set":
				return f"{prefix}Defined {prefix_priv}{_display_name(name)} = {actual!r}"

			return f"{prefix}{prefix_priv}{_display_name(name)} = {actual!r}"

		if kind == "call":
			if payload is not None and payload.get("type") == "class_init":
				cls = str(payload.get("class_name", "")).split(".")[-1]
				inst = payload.get("instance_name")

				args = _payload_args(payload)
				kwargs = _payload_kwargs(payload)

				parts = []

				if args:
					parts.append(", ".join(repr(a) for a in args))

				if kwargs:
					parts.append(", ".join(f"{k}={v!r}" for k, v in kwargs.items()))

				arg_str = ", ".join(parts)
				return f"{prefix}Created new {cls}({arg_str}) as {inst}"

			if name.endswith("__init__"):
				return None

			func_name = _display_name(name)

			if payload is not None:
				args = _payload_args(payload)
				kwargs = _payload_kwargs(payload)

				arg_parts: list[str] = []
				if args:
					arg_parts.append(", ".join(_pretty_arg(a) for a in args))
				if kwargs:
					arg_parts.append(", ".join(f"{k}={v!r}" for k, v in kwargs.items()))

				return f"{prefix}Calling {func_name}({', '.join(arg_parts)})"

			return f"{prefix}Calling {func_name}()"

		if kind == "raise":
			if payload is not None:
				exc = payload.get("exception")
				exc_type = payload.get("exception_type", type(exc).__name__)
				call_sig = payload.get("call_signature")

				func_name = _display_name(str(call_sig).split("(")[0]) if call_sig else _display_name(name)

				return f"{prefix}{func_name}() raised {exc_type}: {exc}"

			return f"{prefix}{_display_name(name)}() raised {value!r}"

		if kind == "yield":
			result = payload.get("value") if payload is not None else value
			return f"{prefix}{_display_name(name)} yielded {result!r}"

		if kind == "return":
			if payload is not None:
				result = payload.get("value")
				call_sig = payload.get("call_signature")

				if call_sig:
					signature = str(call_sig)
					func_name = signature.split("(")[0]
					clean_name = _display_name(func_name)
					args_part = signature[len(func_name) :]

					return f"{prefix}{clean_name}{args_part} returned {result!r}"

				func_name = _display_name(name)
				return f"{prefix}{func_name}() returned {result!r}"

			return f"{prefix}{value!r}"
	# End edu mode

	if kind == "message":
		if not config._g_show_message_meta:
			return f"{value}"

		return f"{prefix}{value}"

	if kind == "change" and payload is not None and "op" in payload:
		formatted = _format_change_payload(name, payload, prefix)
		if formatted is not None:
			return formatted

	if payload is not None and payload.get("type") == "private":
		value = payload["value"]
		payload = _payload_of(value)

	# Nested definition; render signature not payload dict
	if kind == "set" and payload is not None and payload.get("type") == "function":
		defaults = _payload_defaults(payload)
		signature = ", ".join(f"{k}={v!r}" for k, v in defaults.items())

		return f"{prefix}({kind}) {_display_name(name)}({signature})"

	if kind == "raise" and payload is not None:
		exc = payload.get("exception")
		exc_type = payload.get("exception_type", type(exc).__name__)

		args = _payload_args(payload)
		kwargs = _payload_kwargs(payload)

		func_name = _display_name(name)
		payload_str = _format_call_payload(args, kwargs)

		return _format_call_line(prefix, kind, func_name, payload_str, f"-! {exc_type}: {exc}")

	if kind == "yield" and payload is not None and "value" in payload:
		func_name = _display_name(name)
		payload_str = _format_call_payload(_payload_args(payload), _payload_kwargs(payload))

		return _format_call_line(prefix, kind, func_name, payload_str, f"-> {payload['value']!r}")

	if kind == "return" and payload is not None and "value" in payload:
		result = payload["value"]

		args = _payload_args(payload)
		kwargs = _payload_kwargs(payload)

		func_name = _display_name(name)
		payload_str = _format_call_payload(args, kwargs)

		return _format_call_line(prefix, kind, func_name, payload_str, f"-> {result!r}")

	if kind == "call" and payload is not None:
		args = _payload_args(payload)
		kwargs = _payload_kwargs(payload)
		target = payload.get("target")

		func_name = _display_name(name)
		payload_str = _format_call_payload(args, kwargs)

		if target:
			return f"{prefix}({kind}) {target} <- {func_name} {payload_str}".rstrip()
		else:
			return f"{prefix}({kind}) {func_name} {payload_str}".rstrip()

	return f"{prefix}({kind}) {name} = {value!r}"


_DISPLAY_FLAGS = ("show_time", "show_file", "show_lineno")

# The full argument list a formatter may ask for
_FORMATTER_ARGUMENTS = 6


def _formatter_call_shape(func: Formatter) -> FormatterShape:
	try:
		params = list(inspect.signature(func).parameters.values())
	except (TypeError, ValueError):
		# C callables expose no signature; assume full form
		return _FORMATTER_ARGUMENTS, False

	names = {p.name for p in params}

	if any(p.kind is p.VAR_POSITIONAL for p in params):
		positional = _FORMATTER_ARGUMENTS
	else:
		positional = min(
			sum(
				1
				for p in params
				if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD) and p.name not in _DISPLAY_FLAGS
			),
			_FORMATTER_ARGUMENTS,
		)

	takes_flags = any(p.kind is p.VAR_KEYWORD for p in params) or all(flag in names for flag in _DISPLAY_FLAGS)

	return positional, takes_flags


_formatter: Formatter = _default_formatter
_formatter_shape: FormatterShape = (_FORMATTER_ARGUMENTS, True)


def _format_path(filename: str | None) -> str:
	if not filename:
		return ""

	if config._g_path_mode == "absolute":
		return filename

	if config._g_path_mode == "project":
		return _relative_path(filename)

	if config._g_path_mode == "file":
		return os.path.basename(filename)

	return filename


def set_output_formatter(func: Formatter) -> None:
	"""Replace the line formatter"""

	global _formatter, _formatter_shape
	_formatter = func
	_formatter_shape = _formatter_call_shape(func)


def reset_output_formatter() -> None:
	global _formatter, _formatter_shape
	_formatter = _default_formatter
	_formatter_shape = (_FORMATTER_ARGUMENTS, True)


__all__ = [
	"Formatter",
	"FormatterShape",
	"_default_formatter",
	"_format_path",
	"_path",
	"_payload_of",
	"_safe_repr",
	"reset_output_formatter",
	"set_output_formatter",
]
