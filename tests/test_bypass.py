"""
Changes made around a container's logging methods: heapq writes to a list's storage
directly, deques and containers passed in are never wrapped. All are still reported,
written as the call on the line that made them.
"""

import heapq

from collections import deque

from helpers import capture, assert_has, assert_not_has

from logeye import log


def test_heapq_on_a_list_built_in_the_function(capsys):
	@log
	def smallest(values):
		heap = []
		for value in values:
			heapq.heappush(heap, value)
		first = heapq.heappop(heap)
		heapq.heapreplace(heap, 0)
		return first

	assert smallest([5, 1, 4]) == 1

	raw, _ = capture(capsys)

	# Inside a test the name carries the test's own qualname in front
	assert_has(raw, "(change) heappush(")
	assert_has(raw, "smallest.heap, 1) -> [1, 5]")
	assert_has(raw, "(change) heappop(")
	assert_has(raw, "smallest.heap) -> 1 | [4, 5]")
	assert_has(raw, "(change) heapreplace(")
	assert_has(raw, "smallest.heap, 0) -> 4 | [0, 5]")


def test_heapq_on_an_argument_reaches_the_caller(capsys):
	@log
	def make_heap(values):
		heapq.heapify(values)

	data = [3, 1, 2]
	make_heap(data)

	assert data == [1, 3, 2]

	raw, _ = capture(capsys)
	assert_has(raw, "(change) heapify(")
	assert_has(raw, "make_heap.values) -> [1, 3, 2]")


def test_heapq_on_a_logged_list_at_module_level(capsys):
	heap = log([])
	heapq.heappush(heap, 3)
	heapq.heappush(heap, 1)

	raw, _ = capture(capsys)

	assert heap == [1, 3]
	assert_has(raw, "heappush(heap, 1) -> [1, 3]")


def test_educational_mode_tells_heap_operations(capsys):
	@log(mode="edu")
	def schedule():
		tasks = []
		heapq.heappush(tasks, (2, "write"))
		heapq.heappush(tasks, (1, "read"))
		return heapq.heappop(tasks)

	assert schedule() == (1, "read")

	raw, _ = capture(capsys)

	assert_has(raw, "Pushed (1, 'read') onto tasks")
	assert_has(raw, "Popped (1, 'read') from tasks")


def test_deque_operations_are_reported(capsys):
	@log
	def visit():
		queue = deque(["a"])
		queue.append("b")
		first = queue.popleft()
		return first

	assert visit() == "a"

	raw, _ = capture(capsys)

	assert_has(raw, "visit.queue.append('b') -> deque(['a', 'b'])")
	assert_has(raw, "visit.queue.popleft() -> 'a' | deque(['b'])")


def test_methods_logged_by_the_container_are_not_reported_twice(capsys):
	@log
	def build():
		items = []
		items.append(1)
		return items

	build()

	raw, ls = capture(capsys)

	assert sum("append" in line for line in ls) == 1, raw


def test_argument_changed_by_a_method_reads_as_that_call(capsys):
	@log
	def extend(items):
		items.append(3)

	extend([1, 2])

	raw, _ = capture(capsys)
	assert_has(raw, "extend.items.append(3) -> [1, 2, 3]")


def test_unexplained_change_is_reported_as_the_new_value(capsys):
	def grow(target):
		target.append(1)

	@log
	def run(items):
		grow(items)

	run([])

	raw, _ = capture(capsys)

	assert_has(raw, "run.items = [1]")
	assert_not_has(raw, "run.items.grow")
