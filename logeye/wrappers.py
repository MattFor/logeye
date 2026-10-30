from __future__ import annotations

import io
import types

from collections import Counter
from collections.abc import (
	Callable,
	ItemsView,
	Iterable,
	KeysView,
	Mapping,
	Set as AbstractSet,
	ValuesView,
	Iterator,
)

from . import config
from ._compat import override
from .emitter import _emit
from .formatting import _path
from .introspection import _caller_frame, _fresh_binding, _get_location, _observed_call
from .introspection.ast import Operation
from .watcher import _differs
from typing import (
	TYPE_CHECKING,
	Dict,
	Generic,
	List,
	Set,
	SupportsIndex,
	TypeVar,
	cast,
	overload,
)

if TYPE_CHECKING:
	from _typeshed import SupportsKeysAndGetItem
	from typing_extensions import ParamSpec

	P = ParamSpec("P")


class _BaseLogged:
	# Set per instance via object.__setattr__, bypassing the logging __setattr__
	_log_name: str = "set"

	def _remember_shown(self) -> None:
		"""Keep a copy of what the log last showed, to spot changes it was never told of"""

		if isinstance(self, (list, dict, set)):
			object.__setattr__(self, "_shown", self.copy())

	def _logeye_resync(self, filename: str | None, lineno: int | None, local: str) -> None:
		"""
		Report a change made behind this container's back: heapq and other C code
		write to a list's storage directly, never through the methods that log
		"""

		shown = cast(object, getattr(self, "_shown", _MISSING))
		if shown is _MISSING or not _differs(shown, self):
			return

		payload = _observed_change(_observed_call(filename, lineno, local), shown, self)

		_emit(
			"change",
			self._log_name,
			payload if payload is not None else _unwrap_value(self),
			filename=filename,
			lineno=lineno,
			tracked=True,
		)

		self._remember_shown()


# `...` is a legitimate value a caller may pass
_MISSING: object = object()

# Marks an object mid-wrap, so a reference back to it reads as a cycle
_IN_PROGRESS: object = object()

# Have a __dict__ but are not user data
_OPAQUE_TYPES = (
	types.ModuleType,
	types.GeneratorType,
	types.CoroutineType,
	types.AsyncGeneratorType,
	types.FrameType,
	types.TracebackType,
	types.MappingProxyType,
	BaseException,
	io.IOBase,
)

_SCALAR_TYPES = (str, bytes, int, float, bool, complex, type(None))

# Traversal budget for patho graphs
_MAX_WRAPPED_NODES = 2048

T = TypeVar("T")
K = TypeVar("K")
V = TypeVar("V")
L = TypeVar("L", bound=_BaseLogged)

# dict.pop fallback, independent of the value type
D = TypeVar("D")


@overload
def _unwrap_value(value: LoggedObject[T], _seen: set[int] | None = ...) -> dict[str, object]: ...


@overload
def _unwrap_value(value: LoggedList[T], _seen: set[int] | None = ...) -> list[T]: ...


@overload
def _unwrap_value(value: LoggedDict[K, V] | dict[K, V], _seen: set[int] | None = ...) -> dict[K, V]: ...


@overload
def _unwrap_value(value: LoggedSet[T] | set[T], _seen: set[int] | None = ...) -> set[T]: ...


@overload
def _unwrap_value(value: tuple[T, ...], _seen: set[int] | None = ...) -> tuple[T, ...]: ...


@overload
def _unwrap_value(value: object, _seen: set[int] | None = ...) -> object: ...


def _unwrap_value(value: object, _seen: set[int] | None = None) -> object:
	"""Recursively unwrap logged containers into plain values, rendering cycles as a marker"""

	if isinstance(value, _SCALAR_TYPES):
		return value

	if _seen is None:
		_seen = set()

	obj_id = id(value)
	if obj_id in _seen:
		return "<cycle>"

	_seen.add(obj_id)
	try:
		# Display path: every branch rebuilds a plain container
		if isinstance(value, LoggedObject):
			# noinspection PyUnnecessaryCast
			return cast("LoggedObject[object]", value)._unwrap(_seen)

		if isinstance(value, (LoggedList, list)):
			# noinspection PyUnnecessaryCast
			return [_unwrap_value(v, _seen) for v in cast("list[object]", value)]

		if isinstance(value, (LoggedDict, dict)):
			# noinspection PyUnnecessaryCast
			items = cast("dict[object, object]", value).items()
			return {k: _unwrap_value(v, _seen) for k, v in items}

		if isinstance(value, (LoggedSet, set)):
			# noinspection PyUnnecessaryCast
			return {_unwrap_value(v, _seen) for v in cast("set[object]", value)}

		if isinstance(value, tuple):
			# noinspection PyUnnecessaryCast
			return tuple(_unwrap_value(v, _seen) for v in cast("tuple[object, ...]", value))

		return value
	finally:
		_seen.discard(obj_id)


def _emit_change(
	name: str,
	op: str,
	state: object = None,
	filename: str | None = None,
	lineno: int | None = None,
	**details: object,
) -> None:
	"""Emit a mutation event with a readable payload"""

	if config._g_enabled:
		payload: dict[str, object] = {"op": op}

		for key, value in details.items():
			payload[key] = _unwrap_value(value)

		if state is not None:
			payload["state"] = _unwrap_value(state)

		_emit("change", name, payload, filename=filename, lineno=lineno, tracked=True)

	# Even when not shown, so it is not reported later as a change made behind its back
	if isinstance(state, _BaseLogged):
		state._remember_shown()


def _delta(before: object, after: object) -> tuple[list[object], list[object]] | None:
	"""What went in and what came out, ignoring order; None when that cannot be told"""

	if isinstance(before, Mapping) or isinstance(after, Mapping):
		return None

	try:
		# noinspection PyUnnecessaryCast
		counts = Counter(cast("Iterable[object]", after))
		# noinspection PyUnnecessaryCast
		counts.subtract(Counter(cast("Iterable[object]", before)))
	except TypeError:
		# Unhashable elements
		return None

	added = [item for item, n in counts.items() for _ in range(n)]
	removed = [item for item, n in counts.items() for _ in range(-n)]

	return added, removed


def _observed_change(operation: Operation | None, before: object, after: object) -> dict[str, object] | None:
	"""
	A change noticed only afterwards, described as the call on its line that made it
	None when no call there explains it; it is then reported as the new value
	"""

	if operation is None:
		return None

	op, function, arguments = operation

	payload: dict[str, object] = {
		"op": op,
		"observed": True,
		"function": function,
		"arguments": arguments,
	}

	delta = _delta(before, after)
	if delta is not None:
		payload["added"] = [_unwrap_value(item) for item in delta[0]]
		payload["removed"] = [_unwrap_value(item) for item in delta[1]]

	payload["state"] = _unwrap_value(after)
	return payload


@overload
def _wrap_value(
	value: Callable[P, T],
	name: str | None = ...,
	seen: dict[int, object] | None = ...,
	deep: bool = ...,
) -> Callable[P, T]: ...


@overload
def _wrap_value(
	value: list[T],
	name: str | None = ...,
	seen: dict[int, object] | None = ...,
	deep: bool = ...,
) -> LoggedList[T]: ...


@overload
def _wrap_value(
	value: Mapping[K, V],
	name: str | None = ...,
	seen: dict[int, object] | None = ...,
	deep: bool = ...,
) -> LoggedDict[K, V]: ...


@overload
def _wrap_value(
	value: set[T],
	name: str | None = ...,
	seen: dict[int, object] | None = ...,
	deep: bool = ...,
) -> LoggedSet[T]: ...


@overload
def _wrap_value(
	value: L,
	name: str | None = ...,
	seen: dict[int, object] | None = ...,
	deep: bool = ...,
) -> L: ...


@overload
def _wrap_value(
	value: T,
	name: str | None = ...,
	seen: dict[int, object] | None = ...,
	deep: bool = ...,
) -> T: ...


def _wrap_value(
	value: object,
	name: str | None = None,
	seen: dict[int, object] | None = None,
	deep: bool = True,
) -> object:
	"""
	A logging copy of a list / dict / set, and of the containers inside it when `deep`
	Anything else comes back as is: swapping an object for a stand-in would lose its
	class, its methods and every other reference to it
	"""
	if callable(value):
		return value

	if isinstance(value, _BaseLogged):
		return value

	if isinstance(value, _SCALAR_TYPES):
		return value

	if isinstance(value, _OPAQUE_TYPES):
		return value

	if seen is None:
		seen = {}

	obj_id = id(value)
	recorded = seen.get(obj_id)

	# Cycle, so hand back the real object and keep the caller's structure working
	if recorded is _IN_PROGRESS:
		return value

	if recorded is not None:
		# Finished entry: (original, wrapper)
		return cast("tuple[object, object]", recorded)[1]

	if len(seen) >= _MAX_WRAPPED_NODES:
		return value

	safe_name = name or "NO_NAME_ERR"

	wrapped: object

	seen[obj_id] = _IN_PROGRESS
	try:
		if isinstance(value, Mapping):
			# noinspection PyUnnecessaryCast
			wrapped = LoggedDict(cast("Mapping[object, object]", value), safe_name, seen, deep)
		elif isinstance(value, list):
			# noinspection PyUnnecessaryCast
			wrapped = LoggedList(cast("list[object]", value), name=safe_name, _seen=seen, _deep=deep)
		elif isinstance(value, set):
			# noinspection PyUnnecessaryCast
			wrapped = LoggedSet(cast("set[object]", value), name=safe_name, _seen=seen)
		else:
			wrapped = value
	except Exception:
		_ = seen.pop(obj_id, None)
		raise

	seen[obj_id] = (value, wrapped)
	return wrapped


_CONTAINER_TYPES = (list, dict, set)


def _wrap_assigned(value: T, name: str) -> T:
	"""
	Wrap a container about to be stored, but only one the statement itself just built
	One that already existed may be referenced elsewhere, and a copy would split them
	"""

	if type(value) not in _CONTAINER_TYPES:
		return value

	frame = _caller_frame()
	try:
		depth = _fresh_binding(*_get_location(frame))
	finally:
		del frame

	if not depth:
		return value

	return _wrap_value(value, name=name, deep=depth > 1)


def _register_root(seen: dict[int, object], initial: object, wrapper: object) -> None:
	"""Claim `initial` before wrapping children, so a self-reference reads as a cycle"""
	if initial is not None and id(initial) not in seen:
		seen[id(initial)] = (initial, wrapper)


class LoggedObject(_BaseLogged, Generic[T]):
	"""
	Wrapper around mappings / objects that logs every mutation
	Holds data in `_data`, tracks attribute and item changes, wraps nested values
	"""

	# Set in __init__; __setattr__ routes underscore names to object.__setattr__
	_data: dict[str, object]  # pyright: ignore[reportUninitializedInstanceVariable]

	def __init__(
		self,
		initial: T | None = None,
		name: str = "set",
		_seen: dict[int, object] | None = None,
	) -> None:
		if _seen is None:
			_seen = {}

		# object.__setattr__, or the logging __setattr__ would emit during init
		object.__setattr__(self, "_data", {})
		object.__setattr__(self, "_log_name", name)

		# __eq__ / __hash__ defer to this, so `x in some_list` keeps working
		object.__setattr__(self, "_origin", initial)

		if initial is None:
			return

		_register_root(_seen, initial, self)

		items: ItemsView[str, object]

		if isinstance(initial, Mapping):
			# noinspection PyUnnecessaryCast
			items = cast("Mapping[str, object]", initial).items()
		elif hasattr(initial, "__dict__"):
			items = cast("dict[str, object]", cast(object, vars(initial))).items()
		else:
			raise TypeError("LoggedObject can only wrap mappings or objects with __dict__")

		for key, value in items:
			self._data[key] = _wrap_value(value, name=f"{name}.{key}", seen=_seen)

	def _own_data(self) -> dict[str, object]:
		"""Read _data without going through the logging __getattr__"""

		return cast("dict[str, object]", object.__getattribute__(self, "_data"))

	def _own_log_name(self) -> str:
		return cast(str, object.__getattribute__(self, "_log_name"))

	def __getattr__(self, name: str) -> object:
		data = self._own_data()

		if name in data:
			return data[name]

		raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}")

	@override
	def __setattr__(self, name: str, value: object) -> None:
		if name.startswith("_"):
			object.__setattr__(self, name, value)
			return

		data = self._own_data()
		log_name = self._own_log_name()

		wrapped = _wrap_assigned(value, f"{log_name}.{name}")
		data[name] = wrapped

		frame = _caller_frame()
		try:
			filename, lineno = _get_location(frame)

			if callable(wrapped):
				_emit_change(
					f"{log_name}.{name}",
					"setattr",
					state=wrapped,
					filename=filename,
					lineno=lineno,
					value=f"<func {_path(wrapped)}>",
				)
			else:
				_emit_change(
					f"{log_name}.{name}",
					"setattr",
					state=wrapped,
					filename=filename,
					lineno=lineno,
					value=wrapped,
				)
		finally:
			del frame

	def __getitem__(self, key: str) -> object:
		return self._data[key]

	def __setitem__(self, key: str, value: object) -> None:
		log_name = self._own_log_name()
		wrapped = _wrap_assigned(value, f"{log_name}.{key}")
		self._data[key] = wrapped

		frame = _caller_frame()
		try:
			filename, lineno = _get_location(frame)

			_emit_change(
				f"{log_name}.{key}",
				"setitem",
				state=wrapped,
				filename=filename,
				lineno=lineno,
				value=_unwrap_value(value),
			)
		finally:
			del frame

	@override
	def __delattr__(self, name: str) -> None:
		if name.startswith("_"):
			raise AttributeError(name)

		data = self._own_data()
		log_name = self._own_log_name()

		if name not in data:
			raise AttributeError(name)

		del data[name]

		frame = _caller_frame()
		try:
			filename, lineno = _get_location(frame)
			_emit(
				"set",
				f"{log_name}.{name}",
				"<deleted>",
				filename=filename,
				lineno=lineno,
				tracked=True,
			)
		finally:
			del frame

	def __delitem__(self, key: str) -> None:
		log_name = self._own_log_name()
		del self._data[key]

		frame = _caller_frame()
		try:
			filename, lineno = _get_location(frame)
			_emit(
				"set",
				f"{log_name}.{key}",
				"<deleted>",
				filename=filename,
				lineno=lineno,
				tracked=True,
			)
		finally:
			del frame

	def __iter__(self) -> Iterator[str]:
		return iter(self._data)

	def __len__(self) -> int:
		return len(self._data)

	def __contains__(self, key: str) -> bool:
		return key in self._data

	def get(self, key: str, default: object = None) -> object:
		return self._data.get(key, default)

	def keys(self) -> KeysView[object]:
		return self._data.keys()

	def values(self) -> ValuesView[object]:
		return self._data.values()

	def items(self) -> ItemsView[str, object]:
		return self._data.items()

	def _unwrap(self, seen: set[int] | None = None) -> dict[str, object]:
		return {k: _unwrap_value(v, seen) for k, v in self._data.items()}

	def to_dict(self) -> dict[str, object]:
		return _unwrap_value(self)

	@override
	def __eq__(self, other: object) -> bool:
		"""Compare as the wrapped object, or logging changes what the program computes"""

		origin = cast(object, object.__getattribute__(self, "_origin"))

		if isinstance(other, LoggedObject):
			# noinspection PyUnnecessaryCast
			wrapper = cast("LoggedObject[object]", other)
			other = cast(object, object.__getattribute__(wrapper, "_origin"))

		if origin is None:
			return self is other

		return not _differs(origin, other)

	@override
	def __ne__(self, other: object) -> bool:
		result = self.__eq__(other)
		return result if result is NotImplemented else not result

	@override
	def __hash__(self) -> int:
		origin = cast(object, object.__getattribute__(self, "_origin"))

		try:
			return hash(origin)
		except TypeError:
			# Unhashable payload, fall back to identity
			return object.__hash__(self)

	@override
	def __repr__(self) -> str:
		return repr(self.to_dict())

	@override
	def __dir__(self) -> list[str]:
		return sorted(set(super().__dir__()) | set(self._data.keys()))


# typing.List / Dict / Set bases, since list[T] is not subscriptable on 3.8
class LoggedList(List[T], _BaseLogged, Generic[T]):
	"""List wrapper that logs mutations like append, sort, pop, extend"""

	def __init__(
		self,
		initial: Iterable[T] | None = None,
		name: str = "set",
		_seen: dict[int, object] | None = None,
		_deep: bool = True,
	) -> None:
		if _seen is None:
			_seen = {}

		object.__setattr__(self, "_log_name", name)

		if initial is None:
			initial = []

		super().__init__()
		_register_root(_seen, initial, self)

		if _deep:
			super().__init__([_wrap_value(v, name=f"{name}[{i}]", seen=_seen) for i, v in enumerate(initial)])
		else:
			super().__init__(initial)

		self._remember_shown()

	def _emit(self, op: str, **details: object) -> None:
		frame = _caller_frame()
		try:
			filename, lineno = _get_location(frame)
			_emit_change(
				self._log_name,
				op,
				state=self,
				filename=filename,
				lineno=lineno,
				**details,
			)
		finally:
			del frame

	@overload
	def __setitem__(self, key: SupportsIndex, value: T, /) -> None: ...

	@overload
	def __setitem__(self, key: slice, value: Iterable[T], /) -> None: ...

	@override
	def __setitem__(self, key: SupportsIndex | slice, value: T | Iterable[T], /) -> None:
		if isinstance(key, slice):
			# noinspection PyUnnecessaryCast
			items = list(cast("Iterable[T]", value))
			super().__setitem__(key, items)
			self._emit("setitem", key=str(key), value=items)
			return

		# noinspection PyUnnecessaryCast
		single = cast("T", value)
		super().__setitem__(key, _wrap_assigned(single, f"{self._log_name}[{key}]"))

		frame = _caller_frame()
		try:
			filename, lineno = _get_location(frame)

			full_name = f"{self._log_name}.{key}"

			_emit(
				"change",
				full_name,
				{
					"op": "setitem",
					"value": _unwrap_value(single),
					"state": _unwrap_value(self),
				},
				filename=filename,
				lineno=lineno,
				tracked=True,
			)
		finally:
			del frame

		self._remember_shown()

	@override
	def __delitem__(self, key: SupportsIndex | slice, /) -> None:
		super().__delitem__(key)
		self._emit("delitem", key=key)

	# Stored as passed; a copy would no longer be the object the caller holds

	@override
	def append(self, value: T) -> None:
		super().append(value)
		self._emit("append", value=value)

	@override
	def extend(self, iterable: Iterable[T]) -> None:
		items = list(iterable)
		super().extend(items)
		self._emit("extend", value=items)

	@override
	def insert(self, index: SupportsIndex, value: T) -> None:
		super().insert(index, value)
		self._emit("insert", index=index, value=value)

	@override
	def pop(self, index: SupportsIndex = -1) -> T:
		value = super().pop(index)
		self._emit("pop", index=index, value=value)
		return value

	@override
	def remove(self, value: T) -> None:
		super().remove(value)
		self._emit("remove", value=value)

	@override
	def clear(self) -> None:
		super().clear()
		self._emit("clear")

	@override
	def sort(self, *args: object, **kwargs: object) -> None:
		sort_impl = cast("Callable[..., None]", super().sort)
		sort_impl(*args, **kwargs)

		self._emit("sort", args=args, kwargs=kwargs)

	@override
	def reverse(self) -> None:
		super().reverse()
		self._emit("reverse")

	@override
	def __iadd__(self, other: Iterable[T], /) -> LoggedList[T]:
		self.extend(other)
		return self

	@override
	def __imul__(self, other: SupportsIndex, /) -> LoggedList[T]:
		_ = super().__imul__(other)
		self._emit("imul", factor=other)
		return self

	def to_list(self) -> list[T]:
		return _unwrap_value(self)

	@override
	def __repr__(self) -> str:
		return repr(self.to_list())


class LoggedDict(Dict[K, V], _BaseLogged, Generic[K, V]):
	"""Dict wrapper that logs mutations like setitem, update, pop, clear"""

	def __init__(
		self,
		initial: Mapping[K, V] | Iterable[tuple[K, V]] | None = None,
		name: str = "set",
		_seen: dict[int, object] | None = None,
		_deep: bool = True,
		/,
		**kwargs: object,
	) -> None:
		# Positional-only, so LoggedDict(a=1, name="Alice") keeps "name" as a key
		if _seen is None:
			_seen = {}

		object.__setattr__(self, "_log_name", name)

		source: Mapping[K, V] | Iterable[tuple[K, V]] = cast("Mapping[K, V]", {}) if initial is None else initial

		pairs: list[tuple[object, object]]

		if isinstance(source, Mapping):
			# noinspection PyUnnecessaryCast
			pairs = list(cast("Mapping[object, object]", source).items())
		else:
			# noinspection PyUnnecessaryCast
			pairs = list(cast("Iterable[tuple[object, object]]", source))

		pairs += list(kwargs.items())

		super().__init__()
		_register_root(_seen, cast(object, source), self)
		for k, v in pairs:
			# super() skips the logging __setitem__
			# noinspection PyUnnecessaryCast
			value = cast("V", v)
			super().__setitem__(
				cast("K", k),
				_wrap_value(value, name=f"{name}.{k}", seen=_seen) if _deep else value,
			)

		self._remember_shown()

	def _emit(self, op: str, **details: object) -> None:
		frame = _caller_frame()
		try:
			filename, lineno = _get_location(frame)
			_emit_change(
				self._log_name,
				op,
				state=self,
				filename=filename,
				lineno=lineno,
				**details,
			)
		finally:
			del frame

	@override
	def __setitem__(self, key: K, value: V) -> None:
		super().__setitem__(key, _wrap_assigned(value, f"{self._log_name}.{key}"))
		frame = _caller_frame()

		try:
			filename, lineno = _get_location(frame)

			full_name = f"{self._log_name}.{key}"

			_emit(
				"change",
				full_name,
				{
					"op": "setitem",
					"value": _unwrap_value(value),
					"state": _unwrap_value(self),
				},
				filename=filename,
				lineno=lineno,
				tracked=True,
			)
		finally:
			del frame

		self._remember_shown()

	@override
	def __delitem__(self, key: K) -> None:
		super().__delitem__(key)
		self._emit("delitem", key=key)

	def __getattr__(self, name: str) -> V:
		# d.name reads d["name"]
		try:
			# noinspection PyUnnecessaryCast
			return self[cast("K", name)]
		except KeyError as e:
			raise AttributeError(name) from e

	@override
	def __setattr__(self, name: str, value: V) -> None:
		if name.startswith("_"):
			object.__setattr__(self, name, value)
			return

		# noinspection PyUnnecessaryCast
		self[cast("K", name)] = value

	@override
	def __delattr__(self, name: str) -> None:
		if name.startswith("_"):
			raise AttributeError(name)

		# noinspection PyUnnecessaryCast
		del self[cast("K", name)]

	@override
	def update(
		self,
		*args: SupportsKeysAndGetItem[K, V] | Iterable[tuple[K, V]],
		**kwargs: V,
	) -> None:
		data: dict[K, V] = {}

		for source in args:
			data.update(source)

		# noinspection PyUnnecessaryCast
		data.update(cast("dict[K, V]", kwargs))

		# Bypass __setitem__ so update logs once, not per key
		super().update(data)

		self._emit("update", value=data)

	@override
	def __ior__(self, other: SupportsKeysAndGetItem[K, V] | Iterable[tuple[K, V]], /) -> LoggedDict[K, V]:
		# dict's own |= would bypass update() and log nothing
		self.update(other)
		return self

	@overload
	def setdefault(self: LoggedDict[K, V | None], key: K, default: None = None, /) -> V | None: ...

	@overload
	def setdefault(self, key: K, default: V, /) -> V: ...

	@override
	def setdefault(self, key: K, default: V | None = None, /) -> V | None:
		if key in self:
			return self[key]

		# noinspection PyUnnecessaryCast
		super().__setitem__(key, cast("V", default))
		self._emit("setdefault", key=key, value=default)
		return default

	@overload
	def pop(self, key: K, /) -> V: ...

	@overload
	def pop(self, key: K, default: V, /) -> V: ...

	@overload
	def pop(self, key: K, default: D, /) -> V | D: ...

	@override
	def pop(self, key: K, default: object = _MISSING, /) -> object:
		if default is _MISSING:
			value = super().pop(key)
			self._emit("pop", key=key, value=value)
			return value

		# noinspection PyUnnecessaryCast
		value = super().pop(key, cast("V", default))
		self._emit("pop", key=key, value=value)
		return value

	@override
	def popitem(self) -> tuple[K, V]:
		item = super().popitem()
		self._emit("popitem", value=item)
		return item

	@override
	def clear(self) -> None:
		super().clear()
		self._emit("clear")

	def to_dict(self) -> dict[K, V]:
		return _unwrap_value(self)

	@override
	def __repr__(self) -> str:
		return repr(self.to_dict())


class LoggedSet(Set[T], _BaseLogged, Generic[T]):
	"""Set wrapper that logs mutations like add, remove, update, clear"""

	def __init__(
		self,
		initial: Iterable[T] | None = None,
		name: str = "set",
		_seen: dict[int, object] | None = None,
	) -> None:
		if _seen is None:
			_seen = {}

		object.__setattr__(self, "_log_name", name)

		if initial is None:
			initial = set()

		# Left unwrapped: wrapping breaks hashing and membership
		super().__init__(initial)
		self._remember_shown()

	def _emit(self, op: str, **details: object) -> None:
		frame = _caller_frame()
		try:
			filename, lineno = _get_location(frame)
			_emit_change(
				self._log_name,
				op,
				state=self,
				filename=filename,
				lineno=lineno,
				**details,
			)
		finally:
			del frame

	@override
	def add(self, element: T) -> None:
		super().add(element)
		self._emit("add", value=element)

	@override
	def update(self, *others: Iterable[T]) -> None:
		values: list[T] = []
		for other in others:
			values.extend(other)

		super().update(values)
		self._emit("update", value=values)

	@override
	def discard(self, element: object) -> None:
		super().discard(element)
		self._emit("discard", value=element)

	@override
	def remove(self, element: T) -> None:
		super().remove(element)
		self._emit("remove", value=element)

	@override
	def pop(self) -> T:
		value = super().pop()
		self._emit("pop", value=value)
		return value

	@override
	def clear(self) -> None:
		super().clear()
		self._emit("clear")

	# Iterables are listed first; a generator would be spent before it was logged

	@override
	def difference_update(self, *others: Iterable[object]) -> None:
		listed = [list(o) for o in others]
		super().difference_update(*listed)
		self._emit("difference_update", value=listed)

	@override
	def intersection_update(self, *others: Iterable[object]) -> None:
		listed = [list(o) for o in others]
		super().intersection_update(*listed)
		self._emit("intersection_update", value=listed)

	@override
	def symmetric_difference_update(self, other: Iterable[T], /) -> None:
		listed = list(other)
		super().symmetric_difference_update(listed)
		self._emit("symmetric_difference_update", value=listed)

	@override
	def __ior__(self, other: AbstractSet[T], /) -> LoggedSet[T]:
		self.update(other)
		return self

	@override
	def __iand__(self, other: AbstractSet[object], /) -> LoggedSet[T]:
		_ = super().__iand__(other)
		self._emit("iand", value=list(other))
		return self

	@override
	def __isub__(self, other: AbstractSet[object], /) -> LoggedSet[T]:
		_ = super().__isub__(other)
		self._emit("isub", value=list(other))
		return self

	@override
	def __ixor__(self, other: AbstractSet[T], /) -> LoggedSet[T]:
		_ = super().__ixor__(other)
		self._emit("ixor", value=list(other))
		return self

	def to_set(self) -> set[T]:
		return _unwrap_value(self)

	@override
	def __repr__(self) -> str:
		return repr(self.to_set())


__all__ = [
	"LoggedDict",
	"LoggedList",
	"LoggedObject",
	"LoggedSet",
	"_BaseLogged",
	"_observed_change",
	"_unwrap_value",
	"_wrap_assigned",
	"_wrap_value",
]
