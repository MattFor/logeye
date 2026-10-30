"""
Every mutating method of the logging containers: it must do exactly what the plain
container does, and say so in the log
"""

import sys
import operator

import pytest

from helpers import capture, assert_has, assert_not_has

from logeye.wrappers import LoggedDict, LoggedList, LoggedObject, LoggedSet


def _check(capsys, make, wrap, operation, expected):
	plain = make()
	logged = wrap(make())

	assert operation(logged) == operation(plain)
	assert logged == plain

	raw, _ = capture(capsys)
	assert_has(raw, expected)


@pytest.mark.parametrize(
	"operation, expected",
	[
		(lambda c: c.append(4), "items.append(4) -> [1, 2, 3, 4]"),
		(lambda c: c.extend([4, 5]), "items.extend([4, 5])"),
		(lambda c: c.insert(0, 9), "items.insert(0, 9) -> [9, 1, 2, 3]"),
		(lambda c: c.pop(), "items.pop() -> 3 | [1, 2]"),
		(lambda c: c.pop(0), "items.pop(0) -> 1 | [2, 3]"),
		(lambda c: c.remove(2), "items.remove(2) -> [1, 3]"),
		(lambda c: c.clear(), "items.clear() -> []"),
		(lambda c: c.sort(reverse=True), "items.sort(reverse=True) -> [3, 2, 1]"),
		(lambda c: c.reverse(), "items.reverse() -> [3, 2, 1]"),
		(lambda c: c.__setitem__(0, 7), "items.0 = 7"),
		(lambda c: c.__setitem__(slice(0, 2), [8, 8]), "[8, 8, 3]"),
		(lambda c: c.__delitem__(0), "items.delitem(0) -> [2, 3]"),
		(lambda c: operator.iadd(c, [4]) and None, "items.extend([4])"),
		(lambda c: operator.imul(c, 2) and None, "items.imul(2) -> [1, 2, 3, 1, 2, 3]"),
	],
)
def test_list_operations(capsys, operation, expected):
	_check(
		capsys,
		lambda: [1, 2, 3],
		lambda value: LoggedList(value, name="items"),
		operation,
		expected,
	)


@pytest.mark.parametrize(
	"operation, expected",
	[
		(lambda c: c.__setitem__("d", 4), "table.d = 4"),
		(lambda c: c.__delitem__("a"), "table.delitem('a')"),
		(lambda c: c.update({"z": 1}), "table.update({'z': 1})"),
		pytest.param(
			lambda c: operator.ior(c, {"z": 1}) and None,
			"table.update({'z': 1})",
			marks=pytest.mark.skipif(sys.version_info < (3, 9), reason="dict |= is 3.9+"),
		),
		(lambda c: c.setdefault("q", 5), "table.setdefault('q', 5)"),
		(lambda c: c.pop("a"), "table.pop('a') -> 1 | {'b': 2, 'c': 3}"),
		(lambda c: c.pop("missing", None), "table.pop('missing') -> None"),
		(lambda c: c.popitem(), "table.popitem() -> ('c', 3) | {'a': 1, 'b': 2}"),
		(lambda c: c.clear(), "table.clear() -> {}"),
	],
)
def test_dict_operations(capsys, operation, expected):
	_check(
		capsys,
		lambda: {"a": 1, "b": 2, "c": 3},
		lambda value: LoggedDict(value, "table"),
		operation,
		expected,
	)


def test_dict_attribute_access(capsys):
	table = LoggedDict({"a": 1}, "table")

	table.b = 2
	assert table.b == 2

	del table.a
	assert dict(table) == {"b": 2}

	with pytest.raises(AttributeError):
		_ = table.missing

	raw, _ = capture(capsys)

	assert_has(raw, "table.b = 2")
	assert_has(raw, "table.delitem('a')")


def test_dict_setdefault_on_an_existing_key_changes_nothing(capsys):
	table = LoggedDict({"a": 1}, "table")

	assert table.setdefault("a", 5) == 1

	raw, _ = capture(capsys)
	assert raw == ""


@pytest.mark.parametrize(
	"operation, expected",
	[
		(lambda c: c.add(4), "tags.add(4) -> {1, 2, 3, 4}"),
		(lambda c: c.update([4], [5]), "tags.update([4, 5])"),
		(lambda c: c.discard(1), "tags.discard(1) -> {2, 3}"),
		(lambda c: c.remove(1), "tags.remove(1) -> {2, 3}"),
		(lambda c: c.pop(), "tags.pop() -> 1 | {2, 3}"),
		(lambda c: c.clear(), "tags.clear() -> set()"),
		(lambda c: c.difference_update([1]), "tags.difference_update([[1]])"),
		(lambda c: c.intersection_update([1, 2]), "tags.intersection_update([[1, 2]])"),
		(
			lambda c: c.symmetric_difference_update([3, 4]),
			"tags.symmetric_difference_update([3, 4]) -> {1, 2, 4}",
		),
		(lambda c: operator.ior(c, {4}) and None, "tags.update([4])"),
		(lambda c: operator.iand(c, {1}) and None, "tags.iand([1]) -> {1}"),
		(lambda c: operator.isub(c, {1}) and None, "tags.isub([1]) -> {2, 3}"),
		(lambda c: operator.ixor(c, {3, 4}) and None, "tags.ixor("),
	],
)
def test_set_operations(capsys, operation, expected):
	_check(
		capsys,
		lambda: {1, 2, 3},
		lambda value: LoggedSet(value, name="tags"),
		operation,
		expected,
	)


def test_logged_object_reads_like_a_mapping(capsys):
	config = LoggedObject({"debug": True, "port": 80}, name="config")

	assert list(config) == ["debug", "port"]
	assert len(config) == 2
	assert "port" in config
	assert config.get("port") == 80
	assert config.get("missing", 1) == 1
	assert list(config.keys()) == ["debug", "port"]
	assert list(config.values()) == [True, 80]
	assert list(config.items()) == [("debug", True), ("port", 80)]
	assert config["debug"] is True
	assert config.to_dict() == {"debug": True, "port": 80}
	assert repr(config) == "{'debug': True, 'port': 80}"
	assert "port" in dir(config)

	with pytest.raises(AttributeError):
		_ = config.missing

	assert capture(capsys)[0] == ""


def test_logged_object_deletions_are_logged(capsys):
	config = LoggedObject({"a": 1, "b": 2}, name="config")

	del config.a
	del config["b"]

	assert len(config) == 0

	with pytest.raises(AttributeError):
		del config.missing

	raw, _ = capture(capsys)

	assert_has(raw, "config.a = '<deleted>'")
	assert_has(raw, "config.b = '<deleted>'")


def test_logged_object_private_attributes_are_not_logged(capsys):
	config = LoggedObject({"a": 1}, name="config")
	config._cache = 5

	assert config._cache == 5
	assert_not_has(capture(capsys)[0], "_cache")

	with pytest.raises(AttributeError):
		del config._cache


def test_logged_object_hashes_like_what_it_wraps():
	class Point:
		def __init__(self):
			self.x = 1

	point = Point()
	assert hash(LoggedObject(point, name="point")) == hash(point)

	# A dict cannot be hashed; the wrapper falls back to its own identity
	assert isinstance(hash(LoggedObject({"k": 1}, name="mapping")), int)


def test_logged_object_wrapping_a_non_mapping_without_attributes_fails():
	with pytest.raises(TypeError):
		LoggedObject(42, name="number")
