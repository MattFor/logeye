from __future__ import annotations

import os

from string import Template
from types import FrameType
from typing import Iterator, Mapping

from .._compat import override
from .frames import _caller_frame, _get_location, _relative_path


def _template_namespace(frame: FrameType | None) -> dict[str, object]:
	"""What `$name` can refer to: the caller's scope plus the path variables"""

	if frame is None:
		return {}

	# Frame namespaces hold arbitrary values; Template stringifies them
	namespace: dict[str, object] = {}
	namespace.update(frame.f_globals)
	namespace.update(frame.f_locals)

	filename, _ = _get_location(frame)

	namespace["apath"] = filename or ""
	namespace["rpath"] = _relative_path(filename) if filename else ""
	namespace["fpath"] = os.path.basename(filename) if filename else ""

	return namespace


def _substitute(text: str, namespace: Mapping[str, object]) -> str:
	try:
		return Template(text).safe_substitute(namespace)
	except Exception:
		# A value whose __str__ raises; the message is better unexpanded than lost
		return text


# typing.Mapping: collections.abc.Mapping[...] is not subscriptable on 3.8
class _BraceEscaped(Mapping[str, object]):
	"""A namespace whose values survive a later str.format() as literal text"""

	def __init__(self, namespace: Mapping[str, object]) -> None:
		self._namespace: Mapping[str, object] = namespace

	@override
	def __getitem__(self, key: str) -> str:
		return str(self._namespace[key]).replace("{", "{{").replace("}", "}}")

	@override
	def __iter__(self) -> Iterator[str]:
		return iter(self._namespace)

	@override
	def __len__(self) -> int:
		return len(self._namespace)


def _expand_template(text: str) -> str:
	"""Fill `$name` placeholders from the caller's scope"""

	frame = _caller_frame()
	try:
		return _substitute(text, _template_namespace(frame))
	finally:
		del frame


def _format_message(text: str, *args: object, **kwargs: object) -> str:
	"""
	Render log("...", *args): `$name` from the caller's scope, `{}` from the arguments.
	Both read the template only, so an argument is never searched for `$name`,
	nor a scope value for `{}` fields
	"""

	frame = _caller_frame()
	try:
		namespace = _template_namespace(frame)
	finally:
		del frame

	escaped = _substitute(text, _BraceEscaped(namespace))

	# Then `{name}` may also come from the caller's scope
	for fields in (kwargs, {**namespace, **kwargs}):
		try:
			return escaped.format(*args, **fields)
		except Exception:
			pass

	return _substitute(text, namespace)


__all__ = [
	"_expand_template",
	"_format_message",
]
