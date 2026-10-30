import sys
import json
import functools

import pytest

from logeye import log, watch
from logeye.watcher import _differs
from logeye.wrappers import LoggedObject, _wrap_value

from helpers import (
	capture,
	assert_has,
	assert_not_has,
	assert_has_change,
)


class Mask:
	__slots__ = ("values",)

	def __init__(self, values):
		self.values = list(values)

	def __bool__(self):
		raise ValueError("truth value of an array with more than one element")

	def any(self):
		return any(self.values)


class NestedMask(Mask):
	__slots__ = ()

	def any(self):
		return Mask(self.values)


class ArrayLike:
	__slots__ = ("values",)

	def __init__(self, values):
		self.values = list(values)

	def __ne__(self, other):
		if isinstance(other, ArrayLike):
			return Mask(a != b for a, b in zip(self.values, other.values))
		return Mask(v != other for v in self.values)

	def __eq__(self, other):
		return Mask(not v for v in self.__ne__(other).values)

	__hash__ = None

	def __repr__(self):
		return f"ArrayLike({self.values!r})"


class FrameLike:
	def __init__(self, values):
		self.values = list(values)

	def __ne__(self, other):
		return NestedMask([a != b for a, b in zip(self.values, other.values)])

	def __eq__(self, other):
		return NestedMask([a == b for a, b in zip(self.values, other.values)])

	__hash__ = None


def test_differs_collapses_an_elementwise_mask():
	assert _differs(ArrayLike([1, 2]), ArrayLike([1, 3]))
	assert not _differs(ArrayLike([1, 2]), ArrayLike([1, 2]))


def test_differs_collapses_a_nested_mask():
	assert _differs(FrameLike([1, 2]), FrameLike([1, 3]))
	assert not _differs(FrameLike([1, 2]), FrameLike([1, 2]))


def test_differs_is_identity_first():
	same = ArrayLike([1, 2])
	assert not _differs(same, same)


def test_differs_treats_an_unusable_comparison_as_a_change():
	class Hostile:
		def __ne__(self, other):
			raise RuntimeError("no comparison for you")

		__hash__ = None

	assert _differs(Hostile(), Hostile())


def test_array_like_local_does_not_abort_the_traced_function(capsys):
	@log
	def compute():
		a = ArrayLike([0, 1, 2])
		a = ArrayLike([0, 2, 4])
		return a

	result = compute()

	assert result.values == [0, 2, 4]

	raw, _ = capture(capsys)
	assert_has_change(raw, "a")


def test_array_like_survives_the_global_watcher(capsys):
	def run():
		a = watch(ArrayLike([1, 1]))
		a = ArrayLike([1, 9])
		return a

	assert run().values == [1, 9]

	raw, _ = capture(capsys)

	assert_has_change(raw, "a")


def test_array_like_threshold_falls_back_to_change_detection(capsys):
	@log(threshold=5)
	def compute():
		a = ArrayLike([1, 1])
		a = ArrayLike([1, 2])
		return a

	assert compute().values == [1, 2]

	raw, _ = capture(capsys)
	assert_has_change(raw, "a")


def test_logged_object_equality_survives_an_elementwise_payload():
	wrapped = LoggedObject(FrameLike([1, 2]), name="frame")

	assert wrapped == FrameLike([1, 2])
	assert wrapped != FrameLike([1, 9])


def test_plain_objects_are_never_swapped_for_a_stand_in():
	frame = FrameLike([1, 2])

	assert _wrap_value(frame, name="frame") is frame


def test_builtin_logs_call_and_return(capsys):
	logged = log(len)

	assert logged([1, 2, 3]) == 3

	raw, _ = capture(capsys)

	assert_has(raw, "(call)")
	assert_has(raw, "(return)")
	assert_has(raw, "-> 3")


def test_builtin_method_logs_call_and_return(capsys):
	logged = log("hello".upper)

	assert logged() == "HELLO"

	raw, _ = capture(capsys)

	assert_has(raw, "(call)")
	assert_has(raw, "-> 'HELLO'")


def test_builtin_reports_a_raise_and_still_propagates(capsys):
	logged = log([1, 2, 3].index)

	with pytest.raises(ValueError):
		logged(99)

	raw, _ = capture(capsys)

	assert_has(raw, "(raise)")
	assert_has(raw, "ValueError")


def test_c_callable_keeps_its_return_value_intact():
	assert log(sorted)([3, 1, 2]) == [1, 2, 3]
	assert log(json.dumps)({"a": 1}) == '{"a": 1}'


def test_callable_object_without_a_code_object_logs_its_exit(capsys):
	class Dispatcher:
		def __call__(self, value):
			return value * 2

	logged = log(Dispatcher())

	assert logged(21) == 42

	raw, _ = capture(capsys)

	assert_has(raw, "(return)")
	assert_has(raw, "-> 42")


def test_partial_logs_its_exit(capsys):
	logged = log(functools.partial(max, 10))

	assert logged(4) == 10

	raw, _ = capture(capsys)

	assert_has(raw, "(return)")
	assert_has(raw, "-> 10")


def test_partial_is_named_after_the_function_it_wraps(capsys):
	logged = log(functools.partial(max, 10))

	assert logged(4) == 10

	raw, _ = capture(capsys)

	assert_has(raw, "partial(max)")


def test_callable_object_is_named_after_its_class(capsys):
	class Dispatcher:
		def __call__(self, value):
			return value

	logged = log(Dispatcher())

	assert logged(1) == 1

	raw, _ = capture(capsys)

	assert_has(raw, "Dispatcher")


def test_a_call_without_arguments_has_no_double_space(capsys):
	logged = log("hello".upper)

	assert logged() == "HELLO"

	raw, _ = capture(capsys)

	assert_has(raw, "str.upper -> 'HELLO'")
	assert_not_has(raw, "  ->")


def test_a_repr_keeps_its_own_double_spaces(capsys):
	logged = log("  a  b  ".strip)

	assert logged() == "a  b"

	raw, _ = capture(capsys)

	assert_has(raw, "'a  b'")


def test_builtin_respects_the_state_level(capsys):
	logged = log(len, level="state")

	assert logged([1]) == 1

	raw, _ = capture(capsys)

	assert_not_has(raw, "(call)")
	assert_has(raw, "(return)")


def test_builtin_respects_a_filter(capsys):
	logged = log(len, filter=["nothing_matches"])

	assert logged([1]) == 1

	raw, _ = capture(capsys)

	assert_not_has(raw, "(call)")
	assert_not_has(raw, "(return)")


def test_immutable_c_type_warns_and_is_returned_unchanged():
	with pytest.warns(RuntimeWarning, match="C type"):
		result = log(int)

	assert result is int
	assert int("7") == 7


def test_immutable_c_type_warning_blames_the_caller(recwarn):
	log(int)  # the line the warning must point at

	expected = sys._getframe().f_lineno - 2

	warning = recwarn.pop(RuntimeWarning)

	assert warning.filename == __file__
	assert warning.lineno == expected


def test_patchable_python_class_is_still_instrumented(capsys):
	@log
	class Point:
		def __init__(self, x):
			self.x = x

	p = Point(3)

	assert p.x == 3
	assert type(p) is Point

	raw, _ = capture(capsys)

	assert_has(raw, "Point")


def test_builtin_is_silent_when_logging_is_disabled(capsys):
	from logeye import toggle_logs

	logged = log(len)

	toggle_logs(False)
	try:
		assert logged([1, 2]) == 2
	finally:
		toggle_logs(True)

	raw, _ = capture(capsys)

	assert_not_has(raw, "(call)")
	assert_not_has(raw, "(return)")


def test_builtin_in_educational_mode(capsys):
	from logeye import set_mode

	set_mode("edu")

	logged = log(len)
	assert logged([1, 2, 3]) == 3

	raw, _ = capture(capsys)

	assert_has(raw, "Calling")
	assert_has(raw, "returned 3")


try:
	import numpy
except ImportError:
	numpy = None

needs_numpy = pytest.mark.skipif(numpy is None, reason="numpy is not installed")


@needs_numpy
def test_numpy_array_local_does_not_abort_the_traced_function(capsys):
	@log
	def compute(n):
		a = numpy.arange(n)
		a = a * 2
		return a.sum()

	assert compute(4) == 12

	raw, _ = capture(capsys)

	assert_has_change(raw, "a")


@needs_numpy
def test_numpy_c_function_logs_call_and_return(capsys):
	logged = log(numpy.array)

	result = logged([1, 2, 3])

	assert list(result) == [1, 2, 3]

	raw, _ = capture(capsys)

	assert_has(raw, "(call)")
	assert_has(raw, "(return)")
