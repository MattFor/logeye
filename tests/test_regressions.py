import os
import sys
import json
import inspect
import threading

import pytest

from logeye import log, watch, set_mode, set_output_formatter, stop_watching
from logeye import config, watcher
from logeye.wrappers import LoggedDict, LoggedList, LoggedSet, _wrap_value

from helpers import (
	capture,
	assert_has,
	assert_not_has,
	assert_has_set,
	assert_has_change,
)


def test_final_assignment_is_logged(capsys):
	@log
	def f():
		x = 10
		x += 1
		x += 3

	f()

	raw, _ = capture(capsys)

	assert_has_change(raw, "x", 14)


def test_final_mutation_is_logged(capsys):
	@log
	def f():
		items = []
		items.append(1)

	f()

	raw, _ = capture(capsys)

	assert_has(raw, "append")


def test_line_numbers_point_at_the_real_statement(capsys):
	base = inspect.currentframe().f_lineno

	@log
	def f():
		first = 1  # base + 4
		second = 2  # base + 5
		return first + second

	f()

	raw, _ = capture(capsys)

	assert f":{base + 4} (set)" in raw and "first = 1" in raw, raw
	assert f":{base + 5} (set)" in raw and "second = 2" in raw, raw


def test_traces_function_defined_in_another_module(capsys):
	from external_module import compute

	compute(3)

	raw, _ = capture(capsys)

	assert_has_set(raw, "compute.doubled", 6)
	assert_has_set(raw, "compute.shifted", 7)
	assert_has(raw, "external_module.py")


def test_traces_function_body_inside_a_thread(capsys):
	@log
	def worker(n):
		doubled = n * 2
		return doubled

	thread = threading.Thread(target=worker, args=(4,))
	thread.start()
	thread.join()

	raw, _ = capture(capsys)

	assert_has_set(raw, "worker.doubled", 8)


def test_repeat_calls_still_log_their_body(capsys):
	@log
	def f(a):
		doubled = a * 2
		return doubled

	f(1)
	capture(capsys)

	f(1)

	raw, _ = capture(capsys)

	assert_has(raw, "doubled")
	assert_has(raw, "2")


def test_recursion_logs_every_level(capsys):
	@log
	def countdown(n):
		if n <= 0:
			return 0

		nxt = countdown(n - 1)
		return nxt + n

	countdown(2)

	raw, ls = capture(capsys)

	assert sum("(call)" in line for line in ls) >= 1
	assert_has(raw, "countdown")


def test_custom_formatter_is_actually_used(capsys):
	def formatter(elapsed, kind, name, value, filename, lineno):
		return f"CUSTOM|{kind}|{name}"

	set_output_formatter(formatter)

	log("hello")

	raw, _ = capture(capsys)

	assert raw.startswith("CUSTOM|"), raw


def test_short_custom_formatter_is_supported(capsys):
	def formatter(elapsed, kind, name, value):
		return f"SHORT|{kind}|{value}"

	set_output_formatter(formatter)

	log("hello")

	raw, _ = capture(capsys)

	assert raw.startswith("SHORT|"), raw


def test_raising_function_is_not_reported_as_returning_none(capsys):
	@log
	def boom():
		x = 1
		raise ValueError("kaboom")

	with pytest.raises(ValueError):
		boom()

	raw, _ = capture(capsys)

	assert_has(raw, "(raise)")
	assert_has(raw, "ValueError")
	assert_not_has(raw, "-> None")


def test_caught_exception_still_reports_a_return(capsys):
	@log
	def safe():
		try:
			raise ValueError("handled")
		except ValueError:
			result = "recovered"

		return result

	safe()

	raw, _ = capture(capsys)

	assert_has(raw, "(return)")
	assert_not_has(raw, "(raise)")


def test_generator_body_is_traced(capsys):
	@log
	def gen(n):
		for i in range(n):
			doubled = i * 2
			yield doubled

	assert list(gen(3)) == [0, 2, 4]

	raw, _ = capture(capsys)

	assert_has(raw, "(yield)")
	assert_has(raw, "doubled")
	assert_has(raw, "(return)")


def test_generator_send_round_trip_is_preserved():
	@log
	def echo():
		received = yield 1
		yield received

	generator = echo()

	assert next(generator) == 1
	assert generator.send("payload") == "payload"


def test_async_function_body_is_traced_across_awaits(capsys):
	import asyncio

	@log
	async def accumulate(n):
		total = 0
		for step in range(n):
			total += step
			await asyncio.sleep(0)
		return total

	assert inspect.iscoroutinefunction(accumulate)
	assert asyncio.run(accumulate(3)) == 3

	raw, _ = capture(capsys)

	assert_has(raw, "accumulate.total = 3")
	assert_has(raw, "(return) accumulate args=(3) -> 3")


class _Item:
	def __init__(self, value):
		self.value = value


def test_logged_list_keeps_membership_and_removal():
	first, second = _Item(1), _Item(2)
	wrapped = LoggedList([first, second], name="wrapped")

	assert first in wrapped

	wrapped.remove(first)

	assert first not in wrapped


def test_logged_set_keeps_membership():
	item = _Item(1)
	wrapped = LoggedSet([item], name="wrapped")

	assert item in wrapped


def test_repeated_reference_is_not_replaced_by_a_placeholder():
	shared = {"k": "v"}
	wrapped = LoggedList([shared, shared], name="wrapped")

	assert wrapped.to_list() == [{"k": "v"}, {"k": "v"}]


def test_true_cycle_keeps_the_original_object():
	cyclic = {}
	cyclic["self"] = cyclic

	wrapped = LoggedDict(cyclic, "wrapped")

	assert wrapped["self"] is not None


def test_modules_are_never_wrapped(capsys):
	@log
	def f():
		module = json
		return module

	f()

	raw, ls = capture(capsys)

	assert_not_has(raw, "JSON (JavaScript")
	assert_not_has(raw, "BaseException")
	assert len(ls) < 10, f"expected a handful of lines, got {len(ls)}"


@pytest.mark.parametrize(
	"opaque",
	[
		json,
		(x for x in range(3)),
		ValueError("boom"),
		type("Cls", (), {}).__dict__,
	],
)
def test_opaque_values_pass_through_unwrapped(opaque):
	assert _wrap_value(opaque, name="v") is opaque


def test_shared_references_are_wrapped_once_not_exponentially():
	leaf = {"n": 1}
	level = leaf

	for _ in range(20):
		level = {"a": level, "b": level}

	wrapped = _wrap_value(level, name="deep")

	assert wrapped["a"] is wrapped["b"]


def test_unwrapping_a_cycle_does_not_recurse_forever():
	cyclic = []
	cyclic.append(cyclic)

	wrapped = LoggedList(cyclic, name="wrapped")

	assert wrapped.to_list() == ["<cycle>"]


def test_wrapping_a_cycle_terminates():
	cyclic = {"name": "root"}
	cyclic["self"] = cyclic

	wrapped = _wrap_value(cyclic, name="root")

	assert wrapped["name"] == "root"
	assert repr(wrapped)


def test_educational_mode_honours_filter(capsys):
	@log(mode="edu", filter=["kept"])
	def f():
		kept = 1
		dropped = 2
		return kept + dropped

	f()

	raw, _ = capture(capsys)

	assert_has(raw, "kept")
	assert_not_has(raw, "dropped")


def test_educational_mode_honours_level(capsys):
	@log(mode="edu", level="call")
	def f():
		value = 1
		return value

	f()

	raw, _ = capture(capsys)

	assert_not_has(raw, "Defined")


def test_deferred_options_are_not_consumed_by_another_call(capsys):
	configured = log(mode="edu")

	log("an unrelated message")

	@configured
	def f():
		x = 1
		return x

	f()

	raw, _ = capture(capsys)

	assert_has(raw, "Defined")
	assert_not_has(raw, "(set)")


def test_two_configurations_do_not_interfere(capsys):
	edu = log(mode="edu")
	full = log(mode="full")

	@edu
	def a():
		x = 1
		return x

	@full
	def b():
		y = 2
		return y

	a()
	b()

	raw, _ = capture(capsys)

	assert_has(raw, "Defined")
	assert_has(raw, "(set)")


@pytest.mark.parametrize("shadow", ["args", "kwargs", "tracer", "call_counter"])
def test_locals_shadowing_internal_names_are_logged(capsys, shadow):
	source = "\n".join(
		[
			"@log",
			"def f():",
			f"\t{shadow} = 'visible'",
			f"\treturn {shadow}",
			"f()",
		]
	)

	exec(compile(source, "<audit>", "exec"), {"log": log})

	raw, _ = capture(capsys)

	assert_has(raw, shadow)
	assert_has(raw, "visible")


def test_tuple_assignment_uses_the_real_names(capsys):
	first, second = log(1), log(2)

	raw, _ = capture(capsys)

	assert_has(raw, "first")
	assert_has(raw, "second")
	assert_not_has(raw, "None =")


def test_tuple_assignment_names_survive_a_loop(capsys):
	for _ in range(3):
		first, second = log(1), log(2)

	raw, ls = capture(capsys)

	assert_not_has(raw, "None =")
	assert sum("first" in line for line in ls) == 3
	assert sum("second" in line for line in ls) == 3


def test_modes_do_not_leak_between_threads(capsys):
	@log(mode="edu")
	def educational():
		value = 1
		return value

	@log(mode="full")
	def standard():
		value = 2
		return value

	errors = []

	def hammer(fn):
		try:
			for _ in range(20):
				fn()
		except Exception as exc:
			errors.append(exc)

	threads = [
		threading.Thread(target=hammer, args=(educational,)),
		threading.Thread(target=hammer, args=(standard,)),
	]

	for thread in threads:
		thread.start()

	for thread in threads:
		thread.join()

	assert not errors

	raw, _ = capture(capsys)

	assert_has(raw, "Defined")
	assert_has(raw, "(set)")


def test_decorated_class_keeps_its_identity():
	@log
	class Point:
		def __init__(self, x):
			self.x = x

	point = Point(1)

	assert type(point) is Point
	assert isinstance(point, Point)


def test_decorated_class_supports_slots():
	@log
	class Slotted:
		__slots__ = ("value",)

		def __init__(self, value):
			self.value = value

	assert Slotted(3).value == 3


def test_logging_does_not_trigger_property_getters():
	calls = []

	@log
	class WithProperty:
		def __init__(self):
			self.plain = 1

		@property
		def computed(self):
			calls.append(1)
			return 42

	WithProperty()

	assert calls == []


def test_delete_uses_the_same_name_as_the_set(capsys):
	@log
	class Holder:
		def __init__(self):
			self.value = 1

	holder = Holder()
	capture(capsys)

	del holder.value

	raw, _ = capture(capsys)

	assert_has(raw, "holder.value")


def test_logged_dict_keeps_reserved_looking_keys():
	mapping = LoggedDict(name="Alice", initial=1, other=2)

	assert dict(mapping) == {"name": "Alice", "initial": 1, "other": 2}


def test_logged_dict_pop_accepts_ellipsis_as_a_default():
	mapping = LoggedDict({"a": 1}, "mapping")

	assert mapping.pop("missing", ...) is ...


def test_start_time_is_set_at_import():
	assert config._g_start_time is not None


def test_watch_can_be_uninstalled():
	def run():
		value = watch(1)
		return value

	run()

	assert sys.gettrace() is not None

	stop_watching()

	assert sys.gettrace() is None


def test_tracer_does_not_follow_unwatched_frames():
	seen = []

	def unwatched():
		# No watch() in here, so the tracer must decline this frame
		total = 0
		for i in range(3):
			total += i
		return total

	def run():
		value = watch(1)
		seen.append(unwatched())
		return value

	run()

	assert seen == [3]
	assert watcher._g_watched_names


def test_watch_state_is_capped():
	for index in range(watcher._MAX_TRACKED_CODES + 50):
		source = f"def generated_{index}():\n\treturn {index}\n"
		namespace = {}
		exec(compile(source, f"<generated-{index}>", "exec"), namespace)

		code = namespace[f"generated_{index}"].__code__
		watcher._slot(watcher._g_watched_names, code, set).add("value")

	assert len(watcher._g_watched_names) <= watcher._MAX_TRACKED_CODES


# =====================================
#  1.7.0: bugs found in the 1.6.2 audit
# =====================================


def test_decorated_subclass_of_a_decorated_class_reports_once(capsys):
	@log
	class Base:
		def __init__(self, x):
			self.x = x

	@log
	class Derived(Base):
		pass

	derived = Derived(1)

	raw, ls = capture(capsys)

	assert derived.x == 1
	assert sum("__init__" in line for line in ls) == 1, raw
	assert sum("derived.x = 1" in line for line in ls) == 1, raw


def test_class_with_only_new_still_constructs():
	@log
	class Tag:
		def __new__(cls, value):
			obj = super().__new__(cls)
			obj.value = value
			return obj

	assert Tag(5).value == 5


def test_class_without_init_or_new_still_rejects_arguments():
	@log
	class Empty:
		pass

	with pytest.raises(TypeError):
		Empty(1)


def test_generator_return_value_reaches_yield_from():
	@log
	def inner():
		yield 1
		return "done"

	def outer():
		result = yield from inner()
		yield result

	assert list(outer()) == [1, "done"]


def test_every_throw_reaches_the_generator():
	@log
	def resilient():
		while True:
			try:
				yield "ready"
			except ValueError:
				pass

	generator = resilient()
	next(generator)

	assert generator.throw(ValueError) == "ready"
	assert generator.throw(ValueError) == "ready"

	generator.close()


def test_async_function_stays_a_coroutine_function_and_logs_its_result(capsys):
	import asyncio

	@log
	async def double(x):
		return x * 2

	assert inspect.iscoroutinefunction(double)
	assert asyncio.run(double(2)) == 4

	raw, _ = capture(capsys)

	assert_has(raw, "(call) ")
	assert_has(raw, "double args=(2) -> 4")


def test_educational_mode_never_prints_a_raw_payload(capsys):
	obj = log({"x": 1, "d": {"k": 1}}, mode="edu")
	set_mode("edu")

	try:
		obj.x = 10
		obj.d.update({"k": 2})
		obj.d.clear()
	finally:
		set_mode("full")

	raw, _ = capture(capsys)

	assert_not_has(raw, "'op'")
	assert_has(raw, "obj.x = 10")


def test_in_place_or_on_a_logged_dict_is_logged(capsys):
	mapping = LoggedDict({"a": 1}, "mapping")
	mapping |= {"b": 2}

	raw, _ = capture(capsys)

	assert dict(mapping) == {"a": 1, "b": 2}
	assert_has(raw, "{'a': 1, 'b': 2}")


def test_first_argument_is_kept_whatever_its_type(capsys):
	@log
	def make(kind, value):
		return kind(value)

	@log
	class Unit:
		def __init__(self):
			self.n = 1

	@log
	def show(obj, extra):
		return extra

	make(int, "5")
	show(Unit(), 7)

	raw, _ = capture(capsys)

	assert_has(raw, "make args=(<class 'int'>, '5')")
	assert_has(raw, "show args=(<")


def test_method_of_a_plain_class_does_not_show_self(capsys):
	class Calc:
		@log
		def add(self, a, b):
			return a + b

	assert Calc().add(1, 2) == 3

	raw, _ = capture(capsys)

	assert_has(raw, "add args=(1, 2)")
	assert_not_has(raw, "object at")


def test_source_that_cannot_be_read_logs_a_message_not_a_placeholder(capsys):
	exec("from logeye import watch\nx = watch(5)\n", {})

	raw, _ = capture(capsys)

	assert_not_has(raw, "PLACEHOLDER")
	assert_has(raw, "5")


def test_bare_log_of_a_container_is_a_message(capsys):
	log([1, 2, 3])
	log({"a": 1})

	raw, _ = capture(capsys)

	assert_has(raw, "[1, 2, 3]")
	assert_has(raw, "{'a': 1}")
	assert_not_has(raw, "set =")


def test_format_arguments_are_never_template_expanded(capsys):
	secret = "hunter2"
	log("typed: {}", "$secret")

	raw, _ = capture(capsys)

	assert secret
	assert_has(raw, "typed: $secret")
	assert_not_has(raw, "hunter2")


def test_template_values_are_expanded_once(capsys):
	secret = "hunter2"
	shown = "$secret"
	log("value: $shown")

	raw, _ = capture(capsys)

	assert secret and shown
	assert_has(raw, "value: $secret")


def test_template_values_with_braces_survive_format_arguments(capsys):
	data = {"a": 1}
	log("$data and {}", 2)

	raw, _ = capture(capsys)

	assert data
	assert_has(raw, "{'a': 1} and 2")


def test_logging_a_plain_instance_reports_it(capsys):
	class Plain:
		pass

	instance = log(Plain())

	raw, _ = capture(capsys)

	assert type(instance) is Plain
	assert_has(raw, "instance = <")


def test_watch_inside_a_logged_function_keeps_the_function_traced(capsys):
	@log
	def f():
		x = watch(1)
		x = 2
		return x

	assert f() == 2

	raw, _ = capture(capsys)

	assert_has(raw, "f.x = 2")
	assert_has(raw, "(return) f -> 2")


def test_watch_threshold_applies_inside_a_logged_function(capsys):
	@log
	def f():
		y = 5 | log(threshold=("absolute", 2))
		y += 1
		y += 2
		return y

	f()

	raw, ls = capture(capsys)

	assert sum(".y = 6" in line for line in ls) == 0, raw
	assert sum(".y = 8" in line for line in ls) == 1, raw


def test_a_raising_repr_does_not_crash_the_program(capsys):
	class Broken:
		def __repr__(self):
			raise RuntimeError("repr is broken")

	@log
	def f(obj):
		local = obj
		return 1

	assert f(Broken()) == 1

	raw, _ = capture(capsys)
	assert_has(raw, "could not format")


def test_log_above_staticmethod_and_classmethod(capsys):
	class Tools:
		@log
		@staticmethod
		def increment(x):
			return x + 1

		@log
		@classmethod
		def name(cls):
			return cls.__name__

	assert Tools().increment(1) == 2
	assert Tools.increment(1) == 2
	assert Tools.name() == "Tools"

	raw, _ = capture(capsys)
	assert_has(raw, "increment args=(1) -> 2")


def test_watch_keeps_an_earlier_tracer_working():
	seen = []

	def recorder(frame, event, arg):
		if frame.f_code is helper.__code__:
			seen.append(event)
		return recorder

	def helper():
		value = 1
		return value

	sys.settrace(recorder)
	try:
		x = watch(1)
		helper()
	finally:
		sys.settrace(None)

	assert x == 1
	assert "line" in seen, seen


def test_project_paths_across_windows_drives_do_not_crash(capsys, monkeypatch):
	import os.path

	def no_relative_path(*_):
		raise ValueError("path is on mount 'D:', start on mount 'C:'")

	monkeypatch.setattr(os.path, "relpath", no_relative_path)

	log("relative: $rpath")

	raw, _ = capture(capsys)
	assert_has(raw, "relative: ")


def test_code_under_the_interpreter_prefix_is_not_treated_as_the_stdlib():
	from logeye.introspection.frames import _is_external_code

	assert not _is_external_code(os.path.join(sys.prefix, "src", "app", "main.py"))
	assert _is_external_code(json.__file__)


def test_set_updates_from_generators_log_their_values(capsys):
	wrapped = LoggedSet({1, 2, 3}, name="wrapped")
	wrapped.difference_update(x for x in (1,))

	raw, _ = capture(capsys)

	assert wrapped == {2, 3}
	assert_has(raw, "[[1]]")


def test_nested_function_return_reports_its_own_arguments(capsys):
	@log(mode="edu")
	def hypotenuse(a, b):
		def square(v):
			return v * v

		return (square(a) + square(b)) ** 0.5

	hypotenuse(3, 4)

	raw, _ = capture(capsys)

	assert_has(raw, "hypotenuse.square(3) returned 9")
	assert_has(raw, "hypotenuse.square(4) returned 16")


def test_instance_is_named_after_a_plain_assignment(capsys):
	@log
	class Account:
		def __init__(self):
			self.balance = 0

	savings = Account()
	savings.balance = 5

	raw, _ = capture(capsys)

	assert_has(raw, "savings.balance = 5")
	assert_not_has(raw, "account.balance")


def test_default_pop_reads_as_pop(capsys):
	stack = log([1, 2])
	stack.pop()

	raw, _ = capture(capsys)

	assert_has(raw, "stack.pop() -> 2")


def test_comprehension_loop_variables_are_not_reported_as_locals(capsys):
	@log
	def table(keys):
		distances = {key: 0 for key in keys}
		squares = [n * n for n in range(3)]
		return distances, squares

	table("ab")

	raw, _ = capture(capsys)

	assert_not_has(raw, ".key =")
	assert_not_has(raw, ".n =")
	assert_not_has(raw, "comp>")
	assert_has(raw, ".squares = [0, 1, 4]")


def test_nested_function_inside_a_generator_reports_its_return(capsys):
	@log
	def numbers():
		def double(v):
			return v * 2

		yield double(1)

	assert list(numbers()) == [2]

	raw, _ = capture(capsys)

	assert_has(raw, "(return) numbers.double args=(1) -> 2")


def test_generator_yields_follow_educational_mode(capsys):
	@log(mode="edu")
	def numbers():
		yield 1

	assert list(numbers()) == [1]

	raw, _ = capture(capsys)

	assert_has(raw, "numbers yielded 1")
	assert_not_has(raw, "(yield)")
