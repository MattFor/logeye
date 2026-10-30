from helpers import lines, count, capture, assert_has, assert_set_order, assert_line_count

from logeye import log, l


@log
class User:
	def __init__(self):
		self.name = "Matt"
		self.active = True

	def rename(self, new_name):
		self.name = new_name
		return self.name

	def toggle(self):
		self.active = not self.active
		return self.active


@log
class Counter:
	def __init__(self):
		self.value = 0

	def inc(self):
		self.value += 1
		return self.value

	def inc_twice(self):
		self.inc()
		self.inc()
		return self.value

	def countdown(self, n):
		if n <= 0:
			return 0
		return self.countdown(n - 1) + 1


@log
class Calc:
	def add(self, a, b):
		return a + b

	def make_adder(self, n):
		return lambda x: x + n

	def outer(self, x):
		def inner(y):
			return x + y

		return inner(3)

	def chain(self, x):
		return (lambda y: (lambda z: x + y + z)(2))(1)


@log
class Profile:
	def __init__(self):
		self.user = {"name": "Matt"}
		self.items = []


@log
class Base:
	def __init__(self):
		self.base = 1


@log
class Child(Base):
	def __init__(self):
		super().__init__()
		self.child = 2


@log
class Empty:
	pass


@log
class SelfRef:
	def __init__(self):
		self.me = self


@log
class WithDict:
	def __init__(self):
		self.data = {"a": 1}


@log
class WithFunc:
	def __init__(self):
		self.func = lambda x: x + 1


@log
class WithList:
	def __init__(self):
		self.items = []


@log
class WithProperty:
	def __init__(self):
		self._x = 1

	@property
	def x(self):
		return self._x

	@x.setter
	def x(self, value):
		self._x = value


@log
class WithStatic:
	@staticmethod
	def ping(x):
		return x + 1


@log
class WithClassMethod:
	value = 10

	@classmethod
	def bump(cls, n):
		return cls.value + n


def test_class_init_emits_once(capsys):
	user = l(User())
	out, ls = capture(capsys)

	assert user.name == "Matt"
	assert user.active is True
	assert count(ls, "User.__init__") == 1
	assert count(ls, "name") >= 1
	assert count(ls, "active") >= 1
	assert_has(out, "Matt")
	assert_has(out, "True")


def test_class_attribute_assignment(capsys):
	user = l(User())
	lines(capsys)

	user.name = "For"
	out, ls = capture(capsys)

	assert user.name == "For"
	assert_line_count(ls, 1)
	assert count(ls, "name") == 1
	assert_has(out, "For")


def test_class_attribute_reassign_order(capsys):
	user = l(User())
	lines(capsys)

	user.name = "A"
	user.name = "B"
	out, ls = capture(capsys)

	assert user.name == "B"
	assert count(ls, "name") >= 2
	assert_has(out, "A")
	assert_has(out, "B")
	assert_set_order(ls, "name", "A", "B")


def test_dynamic_attribute_creation(capsys):
	user = l(User())
	lines(capsys)

	user.new_field = 123
	out, ls = capture(capsys)

	assert hasattr(user, "new_field")
	assert user.new_field == 123
	assert count(ls, "new_field") == 1
	assert_has(out, "123")


def test_delete_attribute_emits_deleted_once(capsys):
	user = l(User())
	lines(capsys)

	del user.name
	out, ls = capture(capsys)

	assert not hasattr(user, "name")
	assert count(ls, "deleted") == 1
	assert count(ls, "name") == 1


def test_private_attribute_is_marked(capsys):
	user = l(User())
	lines(capsys)

	user._hidden = 42
	out, ls = capture(capsys)

	assert user._hidden == 42
	assert count(ls, "_hidden") == 1
	assert count(ls, "<priv>") == 0
	assert_has(out, "42")


def test_multiple_instances_stay_separate(capsys):
	u1 = l(User())
	u2 = l(User())
	lines(capsys)

	u1.name = "A"
	u2.name = "B"
	out, ls = capture(capsys)

	assert u1.name == "A"
	assert u2.name == "B"
	assert_has(out, "A")
	assert_has(out, "B")
	assert count(ls, "name") >= 2


def test_multiple_attributes(capsys):
	user = l(User())
	lines(capsys)

	user.age = 20
	user.city = "NY"
	out, ls = capture(capsys)

	assert user.age == 20
	assert user.city == "NY"
	assert count(ls, "age") == 1
	assert count(ls, "city") == 1
	assert_has(out, "20")
	assert_has(out, "NY")


def test_method_mutation(capsys):
	c = l(Counter())
	lines(capsys)

	result = c.inc()
	out, ls = capture(capsys)

	assert result == 1
	assert c.value == 1
	assert count(ls, "value") >= 1
	assert_has(out, "1")
	assert_has(out, "(call)")
	assert_has(out, "inc")
	assert_has(out, "(return)")


def test_multiple_method_calls(capsys):
	c = l(Counter())
	lines(capsys)

	c.inc()
	c.inc()
	out, ls = capture(capsys)

	assert c.value == 2
	assert count(ls, "inc") >= 2
	assert_has(out, "2")


def test_method_mutation_strict_order(capsys):
	c = l(Counter())
	lines(capsys)

	c.inc()
	out, ls = capture(capsys)

	assert len(ls) >= 1
	assert_has(out, "value")
	assert_has(out, "1")


def test_recursive_method_tracking(capsys):
	c = l(Counter())
	lines(capsys)

	result = c.countdown(3)
	out, ls = capture(capsys)

	assert result == 3
	assert count(ls, "countdown") >= 3
	assert_has(out, "3")
	assert_has(out, "2")
	assert_has(out, "1")


def test_recursive_method_zero_base_case(capsys):
	c = l(Counter())
	lines(capsys)

	result = c.countdown(0)
	out, ls = capture(capsys)

	assert result == 0
	assert_has(out, "0")


def test_method_return(capsys):
	c = l(Calc())
	lines(capsys)

	res = c.add(2, 3)
	out, ls = capture(capsys)

	assert res == 5
	assert_has(out, "2")
	assert_has(out, "3")
	assert_has(out, "5")
	assert_has(out, "(call)")
	assert_has(out, "add")
	assert_has(out, "(return)")


def test_method_return_lambda(capsys):
	c = l(Calc())
	lines(capsys)

	f = c.make_adder(4)
	result = f(3)
	out, ls = capture(capsys)

	assert result == 7
	assert_has(out, "make_adder")
	assert_has(out, "4")


def test_nested_method_definition(capsys):
	c = l(Calc())
	lines(capsys)

	res = c.outer(5)
	out, ls = capture(capsys)

	assert res == 8
	assert_has(out, "outer")
	assert_has(out, "inner")
	assert_has(out, "5")
	assert_has(out, "8")


def test_nested_lambda_in_method(capsys):
	c = l(Calc())
	lines(capsys)

	res = c.chain(5)
	out, ls = capture(capsys)

	assert res == 8
	assert_has(out, "chain")
	assert len(ls) >= 1


def test_method_chaining_logs_multiple_steps(capsys):
	c = l(Calc())
	lines(capsys)

	a = c.add(1, 2)
	b = c.add(a, 3)
	out, ls = capture(capsys)

	assert a == 3
	assert b == 6
	assert_has(out, "1")
	assert_has(out, "2")
	assert_has(out, "3")
	assert_has(out, "6")
	assert count(ls, "add") >= 2


def test_method_override(capsys):
	@log
	class A:
		def foo(self):
			return 1

	@log
	class B(A):
		def foo(self):
			return 2

	b = l(B())
	lines(capsys)

	res = b.foo()
	out, ls = capture(capsys)

	assert res == 2
	assert_has(out, "2")
	assert_has(out, "foo")
	assert_has(out, "(call)")
	assert_has(out, "(return)")


def test_inheritance(capsys):
	c = l(Child())
	out, ls = capture(capsys)

	assert c.base == 1
	assert c.child == 2
	assert count(ls, "base") >= 1
	assert count(ls, "child") >= 1


def test_property_setter(capsys):
	obj = l(WithProperty())
	lines(capsys)

	obj.x = 10
	out, ls = capture(capsys)

	assert obj.x == 10
	assert_has(out, "x")
	assert_has(out, "10")


def test_callable_attribute(capsys):
	obj = l(WithFunc())
	lines(capsys)

	obj.func = lambda x: x + 2
	out, ls = capture(capsys)

	assert callable(obj.func)
	assert count(ls, "func") >= 1
	assert_has(out, "<func")


def test_nested_object_mutation_is_logged(capsys):
	p = l(Profile())
	lines(capsys)

	p.user["name"] = "For"
	out, ls = capture(capsys)

	assert p.user["name"] == "For"
	assert_has(out, "user")
	assert_has(out, "name")
	assert_has(out, "For")


def test_list_mutation(capsys):
	obj = l(WithList())
	lines(capsys)

	obj.items.append(1)
	out, ls = capture(capsys)

	assert obj.items == [1]
	assert_has(out.lower(), "append")
	assert_has(out, "1")


def test_dict_mutation(capsys):
	obj = l(WithDict())
	lines(capsys)

	obj.data["a"] = 2
	out, ls = capture(capsys)

	assert obj.data["a"] == 2
	assert_has(out, "data")
	assert_has(out, "2")


def test_overwrite_method(capsys):
	u = l(User())
	lines(capsys)

	u.name = lambda: "test"
	out, ls = capture(capsys)

	assert callable(u.name)
	assert count(ls, "name") == 1
	assert_has(out, "<func")


def test_class_without_init_tracks_new_attrs(capsys):
	e = l(Empty())
	lines(capsys)

	e.x = 1
	out, ls = capture(capsys)

	assert e.x == 1
	assert count(ls, "x") == 1
	assert_has(out, "1")


def test_self_reference_does_not_explode(capsys):
	obj = l(SelfRef())
	out, ls = capture(capsys)

	assert obj.me is obj
	assert count(ls, "me") == 1
	assert len(ls) < 20


def test_static_method_called_on_instance(capsys):
	obj = l(WithStatic())
	lines(capsys)

	res = obj.ping(5)
	out, ls = capture(capsys)

	assert res == 6
	assert_has(out, "ping")


def test_static_method_called_on_class(capsys):
	lines(capsys)

	res = WithStatic.ping(7)
	out, ls = capture(capsys)

	assert res == 8
	assert_has(out, "ping")


def test_class_method_called_on_instance(capsys):
	obj = l(WithClassMethod())
	lines(capsys)

	res = obj.bump(5)
	out, ls = capture(capsys)

	assert res == 15
	assert_has(out, "bump")


def test_class_method_called_on_class(capsys):
	lines(capsys)

	res = WithClassMethod.bump(5)
	out, ls = capture(capsys)

	assert res == 15
	assert_has(out, "bump")


def test_method_local_lambda_tracing(capsys):
	@log
	class LocalLambda:
		def outer(self, n):
			f = lambda x: x + n
			return f(3)

	obj = l(LocalLambda())
	lines(capsys)

	res = obj.outer(4)
	out, ls = capture(capsys)

	assert res == 7
	assert_has(out, "outer")
	assert_has(out, "lambda")


def test_deep_nested_method_definitions(capsys):
	@log
	class Nested:
		def outer(self, x):
			def mid(y):
				def inner(z):
					return x + y + z

				return inner(3)

			return mid(2)

	obj = l(Nested())
	lines(capsys)

	res = obj.outer(1)
	out, ls = capture(capsys)

	assert res == 6
	assert_has(out, "outer")
	assert_has(out, "mid")
	assert_has(out, "inner")
