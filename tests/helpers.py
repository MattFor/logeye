import re


# ===========================
#  CAPTURE / BASIC UTILITIES
# ===========================


def capture(capsys):
	raw = capsys.readouterr().out
	ls = [l.strip() for l in raw.splitlines() if l.strip()]  # noqa: E741
	return raw, ls


def lines(capsys):
	return [l.strip() for l in capsys.readouterr().out.splitlines() if l.strip()]  # noqa: E741


def count(ls, needle):
	return sum(needle in l for l in ls)  # noqa: E741


# ========================
#    GENERIC ASSERTIONS
# ========================


def assert_has(out, needle):
	assert needle in out, f"Missing '{needle}' in:\n{out}"


def assert_not_has(out, needle):
	assert needle not in out, f"Unexpected '{needle}' in:\n{out}"


def assert_line_count(ls, n):
	assert len(ls) == n, f"Expected {n} lines, got {len(ls)}:\n{ls}"


def assert_line_contains(ls, needle):
	assert any(needle in l for l in ls), f"'{needle}' not found in lines:\n{ls}"  # noqa: E741


def assert_line_order(ls, first, second):
	i1 = next(i for i, l in enumerate(ls) if first in l)  # noqa: E741
	i2 = next(i for i, l in enumerate(ls) if second in l and i > i1)  # noqa: E741
	assert i1 < i2, f"Order wrong: '{first}' before '{second}'\n{ls}"


# ===========================
#  VALUE-SPECIFIC ASSERTIONS
# ===========================


def assert_value(out, value):
	assert repr(value) in out or str(value) in out, f"{value!r} not found in:\n{out}"


def assert_values(out, *values):
	for v in values:
		assert_value(out, v)


def assert_set_order(ls, name, first, second):
	def match(line, val):
		return f"{name} = {repr(val)}" in line

	i1 = next(i for i, l in enumerate(ls) if match(l, first))  # noqa: E741
	i2 = next(i for i, l in enumerate(ls) if match(l, second) and i > i1)  # noqa: E741

	assert i1 < i2, f"Wrong order: {first} -> {second}\n{ls}"


def assert_nested_order(ls, first_name, first_value, second_name, second_value):
	def match(line, name, value):
		return name in line and repr(value) in line

	i1 = next(
		i
		for i, l in enumerate(ls)  # noqa: E741
		if match(l, first_name, first_value)
	)

	i2 = next(
		i
		for i, l in enumerate(ls)  # noqa: E741
		if match(l, second_name, second_value) and i > i1
	)

	assert i1 < i2, f"Wrong nested order:\n{first_name}={first_value} -> {second_name}={second_value}\n{ls}"


# ===========================
#   LOG-SPECIFIC ASSERTIONS
# ===========================


def assert_has_call(out, name=None):
	assert "(call)" in out
	if name:
		assert_has(out, name)


def assert_has_return(out, name=None, value=None):
	assert "(return)" in out
	if name:
		assert_has(out, name)
	if value is not None:
		assert_has(out, f"-> {value!r}")


def assert_has_set(out, name=None, value=None):
	assert "(set)" in out
	if name:
		assert_has(out, name)
	if value is not None:
		assert_has(out, repr(value))


def assert_has_change(out, name=None, value=None):
	assert "(change)" in out
	if name:
		assert_has(out, name)
	if value is not None:
		assert_has(out, repr(value))


def assert_args(out, *args):
	if args:
		expected = ", ".join(repr(a) for a in args)
		assert_has(out, f"args=({expected}")


def assert_kwargs(out, **kwargs):
	for k, v in kwargs.items():
		assert_has(out, f"{k}={v!r}")


def assert_return_value(out, value):
	assert_has(out, f"-> {value!r}")


# ===========================
#    NOISE / SAFETY CHECKS
# ===========================


def assert_no_call_noise(out):
	assert_not_has(out, "Calling")


def assert_no_return_noise(out):
	assert_not_has(out, "returned")


def assert_no_internal_leaks(out):
	forbidden = [
		"args",
		"kwargs",
		"call_counter",
		"target_func",
		"_should_emit",
	]
	for f in forbidden:
		assert f".{f} =" not in out, f"Leak: {f}"


# ========================
#     EDUCATIONAL MODE
# ========================


def assert_edu_call(out, name):
	assert_has(out, f"Calling {name}")
	assert_not_has(out, "(call)")


def assert_edu_return(out, name, value):
	assert_has(out, f"{name}() returned {value!r}")
	assert_not_has(out, "(return)")


def assert_edu_define(out, name):
	assert_has(out, "Defined")
	assert_has(out, name)


# ========================
#    REGEX (LAST RESORT)
# ========================


def assert_match(out, pattern):
	assert re.search(pattern, out), f"Pattern not found: {pattern}\n{out}"


__all__ = [
	"capture",
	"lines",
	"count",
	"assert_has",
	"assert_not_has",
	"assert_line_count",
	"assert_line_contains",
	"assert_line_order",
	"assert_value",
	"assert_values",
	"assert_set_order",
	"assert_nested_order",
	"assert_has_call",
	"assert_has_return",
	"assert_has_set",
	"assert_has_change",
	"assert_args",
	"assert_kwargs",
	"assert_return_value",
	"assert_no_call_noise",
	"assert_no_return_noise",
	"assert_no_internal_leaks",
	"assert_edu_call",
	"assert_edu_return",
	"assert_edu_define",
	"assert_match",
]
