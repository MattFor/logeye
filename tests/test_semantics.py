"""
Logging must never change what the program computes.
Every test here runs code under @log and checks the program saw exactly what it
would have seen without it, and that the change was still reported.
"""

import sys

from helpers import capture, assert_has, assert_not_has

from logeye import log


class Point:
	def __init__(self, x, y):
		self.x = x
		self.y = y

	def norm(self):
		return (self.x**2 + self.y**2) ** 0.5


def test_sorting_an_argument_in_place_reaches_the_caller(capsys):
	@log
	def sort_in_place(arr):
		arr.sort()

	data = [3, 1, 2]
	sort_in_place(data)

	assert data == [1, 2, 3]

	raw, _ = capture(capsys)
	assert_has(raw, "sort_in_place.arr.sort() -> [1, 2, 3]")


def test_swapping_elements_of_an_argument_reaches_the_caller(capsys):
	@log(mode="edu")
	def bubble_sort(arr):
		for i in range(len(arr)):
			for j in range(len(arr) - 1 - i):
				if arr[j] > arr[j + 1]:
					arr[j], arr[j + 1] = arr[j + 1], arr[j]

	data = [3, 2, 1]
	bubble_sort(data)

	assert data == [1, 2, 3]

	raw, _ = capture(capsys)
	assert_has(raw, "bubble_sort.arr = [2, 3, 1]")
	assert_has(raw, "bubble_sort.arr = [1, 2, 3]")


def test_mutating_a_dict_argument_reaches_the_caller(capsys):
	@log
	def add_key(d):
		d["b"] = 2

	config = {"a": 1}
	add_key(config)

	assert config == {"a": 1, "b": 2}

	raw, _ = capture(capsys)
	assert_has(raw, "add_key.d = {'a': 1, 'b': 2}")


def test_plain_objects_keep_their_class_and_methods(capsys):
	@log
	def length():
		p = Point(3, 4)
		assert isinstance(p, Point)
		return p.norm()

	assert length() == 5.0


def test_attribute_changes_on_an_argument_reach_the_caller_and_are_logged(capsys):
	@log
	def move(p):
		p.x = 10
		return p

	point = Point(1, 1)
	returned = move(point)

	assert point.x == 10
	assert returned is point

	raw, _ = capture(capsys)
	assert_has(raw, "move.p.x = 10")


def test_aliases_inside_the_function_stay_aliases():
	@log
	def alias():
		a = [1]
		b = a
		b.append(2)
		return a, b

	a, b = alias()

	assert a is b
	assert a == [1, 2]


def test_aliases_on_one_line_stay_aliases():
	@log
	def alias():
		a = []; b = a  # fmt: skip # noqa: E702
		b.append(1)
		return a, b

	a, b = alias()

	assert a is b
	assert a == [1]


def test_appended_objects_are_stored_as_is():
	# The classic backtracking bug must still show under logging
	@log
	def collect():
		results = []
		current = []

		for value in (1, 2):
			current.append(value)
			results.append(current)

		return results, current

	results, current = collect()

	assert results[0] is current
	assert results == [[1, 2], [1, 2]]


def test_comprehensions_of_existing_rows_keep_the_rows():
	grid = [[0], [0]]

	@log
	def rows_of(source):
		rows = [row for row in source]
		rows[0].append(1)
		return rows

	rows = rows_of(grid)

	assert rows[0] is grid[0]
	assert grid[0] == [0, 1]


def test_containers_built_in_the_function_still_report_their_operations(capsys):
	@log
	def build():
		queue = []
		queue.append(1)
		queue.pop(0)
		return queue

	assert build() == []

	raw, _ = capture(capsys)
	assert_has(raw, "build.queue.append(1)")
	assert_has(raw, "build.queue.pop(0)")


def test_read_only_loops_report_nothing_for_the_argument(capsys):
	@log
	def total(values):
		result = 0
		for value in values:
			result += value
		return result

	assert total([1, 2, 3]) == 6

	raw, _ = capture(capsys)
	assert_not_has(raw, "(change) total.values")


def test_return_line_shows_arguments_as_they_were_passed(capsys):
	@log
	def drain(items):
		items.clear()

	drain([1, 2])

	raw, _ = capture(capsys)
	assert_has(raw, "(return) drain args=([1, 2]) -> None")


def test_logged_class_attribute_keeps_the_object_it_was_given():
	@log
	class Box:
		def __init__(self, items):
			self.items = items

	shared = [1]
	box = Box(shared)
	shared.append(2)

	assert box.items is shared
	assert box.items == [1, 2]


def test_explicit_log_list_stores_appended_objects_as_is():
	node = [1]

	queue = log([])
	queue.append(node)
	node.append(2)

	assert queue[0] is node
	assert queue == [[1, 2]]


def test_numpy_like_object_locals_keep_working():
	numpy = __import__("pytest").importorskip("numpy")

	@log
	def scale(n):
		a = numpy.arange(n)
		a = a * 2
		return int(a.sum())

	assert scale(4) == 12


def test_disabled_logging_leaves_class_attributes_alone():
	from logeye import toggle_logs

	@log
	class Holder:
		def __init__(self):
			self.items = []

	toggle_logs(False)
	try:
		holder = Holder()
	finally:
		toggle_logs(True)

	assert type(holder.items) is list


def test_tracing_does_not_leave_a_trace_function_behind():
	@log
	def f():
		x = [1]
		return x

	before = sys.gettrace()
	f()

	assert sys.gettrace() is before
