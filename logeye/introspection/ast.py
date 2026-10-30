from __future__ import annotations

import os
import ast
import time
import linecache

from typing import NamedTuple, Tuple, cast

from .. import config
from types import FrameType
from .frames import _is_library_file

# log() calls per line, for `a, b = log(...), log(...)`; wraps on target count
_call_counter_per_line: dict[tuple[str, int], int] = {}


def _is_user_code(filename: str) -> bool:
	"""True only for user code, not logeye's own frames"""

	if not filename:
		return True

	return not _is_library_file(filename)


def _is_direct_log_call(node: ast.AST) -> bool:
	"""Is this node a direct `log(...)` / `l(...)` call?"""

	return (
		isinstance(node, ast.Call)
		and isinstance(node.func, ast.Name)
		and (node.func.id == "log" or node.func.id == "l")
	)


# ==========================
#  CACHED SOURCE INSPECTION
# ==========================


class _LineInfo(NamedTuple):
	"""What the assignment on a single source line targets"""

	# Target when the value is literally log(...) / l(...) or a `| l` pipe
	log_single: str | None

	# Target for any simple assignment, whatever the right-hand side
	any_single: str | None

	# Tuple-assignment targets, empty when the line is not one
	tuple_names: tuple[str, ...]

	# False when the line could not be read or parsed
	parsed: bool

	# The function a plain call on the right-hand side calls: `x = Foo(...)` -> "Foo"
	callee: str | None = None


_NO_INFO = _LineInfo(None, None, (), False)

# (filename, lineno) -> _LineInfo, invalidated on mtime change
_line_info_cache: dict[tuple[str, int], _LineInfo] = {}
_file_stamp_cache: dict[str, float] = {}

# Seconds between stat() calls on the same file; the watcher asks per line event,
# and stat'ing that often costs more than everything else the tracer does
_STALE_CHECK_INTERVAL = 0.25
_file_checked_at: dict[str, float] = {}


def _file_stamp(filename: str) -> float:
	try:
		return os.stat(filename).st_mtime
	except OSError:
		return 0.0


def _invalidate_if_stale(filename: str) -> None:
	"""Drop cached line info when the file changed on disk"""

	now = time.monotonic()
	if now - _file_checked_at.get(filename, 0.0) < _STALE_CHECK_INTERVAL:
		return

	_file_checked_at[filename] = now

	stamp = _file_stamp(filename)
	if _file_stamp_cache.get(filename) == stamp:
		return

	_file_stamp_cache[filename] = stamp
	_ = _module_cache.pop(filename, None)
	_ = _tables_cache.pop(filename, None)

	for key in [k for k in _line_info_cache if k[0] == filename]:
		del _line_info_cache[key]


def _flatten_target_names(target: ast.expr) -> tuple[str, ...]:
	"""
	Every binding an assignment target introduces, left to right
	Nested targets flatten into one sequence, so `(a, (b, c))` reads as
	("a", "b", "c") and lines up with the log() calls on the right-hand side
	Anything that is not a plain name (obj.attr, items[0]) keeps a blank slot,
	so the positions of the names around it stay correct
	"""

	if isinstance(target, ast.Name):
		return (target.id,)

	if isinstance(target, ast.Starred):
		return _flatten_target_names(target.value)

	if isinstance(target, (ast.Tuple, ast.List)):
		names: list[str] = []

		for element in target.elts:
			names.extend(_flatten_target_names(element))

		return tuple(names)

	# Assignable, but not to a name we can report
	return ("",)


def _targets_of(node: ast.Assign | ast.AnnAssign) -> tuple[str | None, tuple[str, ...]]:
	"""Split an assignment's targets into (single name, unpacked names)"""

	if isinstance(node, ast.AnnAssign):
		target = node.target
		return (target.id if isinstance(target, ast.Name) else None), ()

	if not node.targets:
		return None, ()

	target = node.targets[0]

	if isinstance(target, ast.Name):
		return target.id, ()

	if isinstance(target, (ast.Tuple, ast.List)):
		return None, _flatten_target_names(target)

	return None, ()


def _info_from_statement(stmt: ast.AST) -> _LineInfo | None:
	if not isinstance(stmt, (ast.Assign, ast.AnnAssign)):
		return None

	value = stmt.value
	if value is None:
		return None

	single, tuple_names = _targets_of(stmt)

	log_single = None

	# x = log(...)
	if _is_direct_log_call(value) or (
		isinstance(value, ast.BinOp)
		and isinstance(value.op, ast.BitOr)
		and isinstance(value.right, ast.Name)
		and value.right.id == config._g_log_pipe_name
	):
		log_single = single

	# a, b = log(...), log(...) tuple_names carries the mapping
	if isinstance(value, (ast.Tuple, ast.List)) and tuple_names:
		return _LineInfo(log_single, single, tuple_names, True)

	callee: str | None = None
	if isinstance(value, ast.Call):
		func = value.func
		if isinstance(func, ast.Name):
			callee = func.id
		elif isinstance(func, ast.Attribute):
			callee = func.attr

	return _LineInfo(log_single, single, (), True, callee)


def _analyze_line(filename: str, lineno: int) -> _LineInfo:
	"""What the statement at filename:lineno assigns to"""

	if not filename:
		return _NO_INFO

	_invalidate_if_stale(filename)

	key = (filename, lineno)
	cached = _line_info_cache.get(key)
	if cached is not None:
		return cached

	info = _NO_INFO

	# Fast path: one line
	source = linecache.getline(filename, lineno).strip()
	if source:
		try:
			node = ast.parse(source)
		except SyntaxError:
			node = None

		if node is not None and node.body:
			parsed = _info_from_statement(node.body[0])
			# Parsed fine but not an assignment
			info = parsed if parsed is not None else _LineInfo(None, None, (), True)

	# Slow path: multi-line statement, parse the module once
	if info.any_single is None and not info.tuple_names:
		module = _module_ast(filename)

		if module is not None:
			for node in ast.walk(module):
				if not isinstance(node, (ast.Assign, ast.AnnAssign)):
					continue

				start = node.lineno
				end = getattr(node, "end_lineno", start)

				if not (start <= lineno <= end):
					continue

				parsed = _info_from_statement(node)
				if parsed is not None and (parsed.any_single or parsed.tuple_names):
					info = parsed
					break

	_line_info_cache[key] = info
	return info


# filename -> module AST, invalidated with the line cache
_module_cache: dict[str, ast.Module | None] = {}


def _module_ast(filename: str) -> ast.Module | None:
	if filename in _module_cache:
		return _module_cache[filename]

	tree: ast.Module | None

	try:
		with open(filename, encoding="utf-8") as f:
			tree = ast.parse(f.read())
	except (OSError, SyntaxError, ValueError):
		tree = None

	_module_cache[filename] = tree
	return tree


# What the call that changed a container looked like: `heappush(heap, x)` is
# ("heappush", True, 1) and `queue.popleft()` is ("popleft", False, 0)
Operation = Tuple[str, bool, int]


class _FileTables(NamedTuple):
	"""Per-line facts about one source file, built from a single walk of its AST"""

	# Names each line binds
	assigns: dict[int, frozenset[str]]

	# Names whose object a line may change in place: `x.append(v)`, `x[i] = v`, `f(x)`
	mutates: dict[int, frozenset[str]]

	# Lines that store a container the statement itself just built:
	# line -> (the plain name it binds, None for obj.attr / obj[key]; fresh depth)
	fresh: dict[int, tuple[str | None, int]]

	# Loop variables of list / set / dict comprehensions, which 3.12+ runs in the
	# enclosing frame; they show up among its locals while the line runs
	comprehension: dict[int, frozenset[str]]

	# The call on a line that may have changed a variable's container:
	# line -> {variable: (operation, written as a function?, other arguments)}
	calls: dict[int, dict[str, Operation]]


# filename -> its tables, invalidated with the line cache
_tables_cache: dict[str, _FileTables] = {}

# Displays and comprehensions always build a new container
_FRESH_DISPLAYS = (ast.List, ast.Set, ast.Dict, ast.ListComp, ast.SetComp, ast.DictComp)
_FRESH_CALLS = frozenset({"list", "dict", "set"})

# Element expressions that can hand back an object which already existed
_BORROWING_NODES = (ast.Name, ast.Call, ast.Await, ast.Yield, ast.YieldFrom)

# Only these run between an assignment and the next line event when they share its line
_SIMPLE_STATEMENTS = (
	ast.Expr,
	ast.Assign,
	ast.AugAssign,
	ast.AnnAssign,
	ast.Return,
	ast.Delete,
	ast.Raise,
	ast.Assert,
	ast.Import,
	ast.ImportFrom,
	ast.Global,
	ast.Nonlocal,
	ast.Pass,
	ast.Break,
	ast.Continue,
)

# Passing a container to these, or calling these methods on it, never changes it
_READ_ONLY_CALLS = frozenset(
	{
		"abs", "all", "any", "bool", "dict", "enumerate", "filter", "float",
		"frozenset", "hash", "id", "int", "isinstance", "iter", "len", "list",
		"map", "max", "min", "print", "range", "repr", "reversed", "set",
		"sorted", "str", "sum", "tuple", "type", "zip",
	}
)  # fmt: skip
_READ_ONLY_METHODS = frozenset({"copy", "count", "get", "index", "items", "keys", "values"})

# Functions that rearrange the list they are given, whatever its methods do: heapq
# writes to its storage directly, and these read best as the call that was made
_MUTATING_FUNCTIONS = frozenset(
	{
		"heappush",
		"heappop",
		"heapify",
		"heapreplace",
		"heappushpop",
		"insort",
		"insort_left",
		"insort_right",
		"shuffle",
	}
)


def _fresh_depth_of(value: ast.expr) -> int:
	"""
	How much of the container `value` evaluates to is new: 2 every level, 1 only the
	outermost, 0 none. Only a new object can be swapped for a logging copy unnoticed;
	anything else may be referenced from somewhere the copy would not reach
	"""

	if isinstance(value, ast.Call):
		if not (isinstance(value.func, ast.Name) and value.func.id in _FRESH_CALLS):
			return 0

		# list(x) is a new list holding x's existing elements
		return 1 if value.args or value.keywords else 2

	parts: list[ast.expr | None]

	if isinstance(value, (ast.ListComp, ast.SetComp)):
		parts = [value.elt]
	elif isinstance(value, ast.DictComp):
		parts = [value.value]
	elif isinstance(value, ast.Dict):
		parts = list(value.values)
	elif isinstance(value, (ast.List, ast.Set)):
		parts = list(value.elts)
	else:
		return 0

	borrowed = any(isinstance(node, _BORROWING_NODES) for part in parts if part is not None for node in ast.walk(part))

	return 1 if borrowed else 2


def _base_name(node: ast.expr) -> str | None:
	"""The variable at the root of `a`, `a.b`, `a[0].c`, `*a`"""

	while isinstance(node, (ast.Attribute, ast.Subscript, ast.Starred)):
		node = node.value

	return node.id if isinstance(node, ast.Name) else None


def _mutated_bases(node: ast.AST) -> list[ast.expr]:
	"""Expressions whose object `node` may change in place"""

	if isinstance(node, ast.Call):
		func = node.func

		if isinstance(func, ast.Name) and func.id in _READ_ONLY_CALLS:
			return []

		if isinstance(func, ast.Attribute):
			if func.attr in _READ_ONLY_METHODS:
				return []

			bases = [func.value]
		else:
			bases = []

		return bases + list(node.args) + [kw.value for kw in node.keywords]

	if isinstance(node, (ast.Attribute, ast.Subscript)) and isinstance(node.ctx, (ast.Store, ast.Del)):
		return [node.value]

	if isinstance(node, ast.AugAssign):
		return [node.target]

	return []


def _call_on_variable(node: ast.Call) -> tuple[str, Operation] | None:
	"""The variable a call may change in place, and how the call reads"""

	func = node.func
	arguments = len(node.args) + len(node.keywords)

	callee: str | None = None
	if isinstance(func, ast.Name):
		callee = func.id
	elif isinstance(func, ast.Attribute):
		callee = func.attr

	first = node.args[0] if node.args else None

	# heapq.heappush(heap, x): the list is the first argument
	if callee in _MUTATING_FUNCTIONS and isinstance(first, ast.Name):
		return first.id, (callee, True, arguments - 1)

	# queue.popleft()
	if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.attr not in _READ_ONLY_METHODS:
		return func.value.id, (func.attr, False, arguments)

	return None


def _span(node: ast.AST) -> range:
	start = cast(int, getattr(node, "lineno"))  # noqa: B009 -- ast.AST does not declare lineno
	end = cast("int | None", getattr(node, "end_lineno", None))
	return range(start, (end or start) + 1)


def _build_tables(filename: str) -> _FileTables:
	assigns: dict[int, set[str]] = {}
	mutates: dict[int, set[str]] = {}
	comprehension: dict[int, set[str]] = {}
	calls: dict[int, dict[str, Operation]] = {}
	statements: dict[int, int] = {}
	candidates: list[tuple[ast.stmt, str | None, int]] = []

	module = _module_ast(filename)

	if module is not None:
		for node in ast.walk(module):
			for target in _assignment_targets(node):
				names = {name for name in _flatten_target_names(target) if name}
				if not names:
					continue

				# The target's own span, not the statement's; a `for` header
				# binds on its own line, not down the whole loop body
				for line in _span(target):
					assigns.setdefault(line, set()).update(names)

			for base in _mutated_bases(node):
				name = _base_name(base)
				if name:
					for line in _span(node):
						mutates.setdefault(line, set()).add(name)

			if isinstance(node, ast.Call):
				observed = _call_on_variable(node)
				if observed is not None:
					for line in _span(node):
						calls.setdefault(line, {})[observed[0]] = observed[1]

			if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp)):
				for generator in node.generators:
					for line in _span(node):
						comprehension.setdefault(line, set()).update(
							name for name in _flatten_target_names(generator.target) if name
						)

			if isinstance(node, _SIMPLE_STATEMENTS):
				for line in _span(node):
					statements[line] = statements.get(line, 0) + 1

			if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
				targets = node.targets if isinstance(node, ast.Assign) else [node.target]
				depth = _fresh_depth_of(node.value)

				if len(targets) == 1 and depth:
					target = targets[0]
					bound = target.id if isinstance(target, ast.Name) else None
					candidates.append((node, bound, depth))

	fresh: dict[int, tuple[str | None, int]] = {}

	for statement, bound, depth in candidates:
		lines = _span(statement)

		# `a = []; b = a` aliases before anything gets to look; only a lone statement is safe
		if all(statements.get(line) == 1 for line in lines):
			for line in lines:
				fresh[line] = (bound, depth)

	return _FileTables(
		{line: frozenset(names) for line, names in assigns.items()},
		{line: frozenset(names) for line, names in mutates.items()},
		fresh,
		{line: frozenset(names) for line, names in comprehension.items()},
		calls,
	)


def _tables(filename: str) -> _FileTables:
	"""
	The tables for `filename`. Asked on every line event, so the warm path is dict
	lookups and nothing else; they are only rebuilt when the file changed on disk
	"""

	tables = _tables_cache.get(filename)

	if tables is None or time.monotonic() - _file_checked_at.get(filename, 0.0) >= _STALE_CHECK_INTERVAL:
		_invalidate_if_stale(filename)
		tables = _tables_cache.get(filename)

		if tables is None:
			tables = _tables_cache[filename] = _build_tables(filename)

	return tables


def _assignment_targets(node: ast.AST) -> list[ast.expr]:
	"""The targets a statement binds, or none when it binds nothing"""

	if isinstance(node, ast.Assign):
		return list(node.targets)

	if isinstance(node, (ast.AnnAssign, ast.AugAssign, ast.NamedExpr)):
		return [node.target] if node.value is not None else []

	if isinstance(node, (ast.For, ast.AsyncFor)):
		return [node.target]

	if isinstance(node, (ast.With, ast.AsyncWith)):
		return [item.optional_vars for item in node.items if item.optional_vars]

	return []


_NO_NAMES: frozenset[str] = frozenset()


def _line_assigns(filename: str, lineno: int | None, name: str) -> bool:
	"""Does the assignment at filename:lineno bind `name`?

	Tells a genuine re-assignment apart from a line that merely read the name,
	so watching can report `x = 1` twice in a row instead of swallowing the second
	"""

	if not filename or lineno is None:
		return False

	# Watched names are bare locals; a dotted one never matches a target
	return name in _tables(filename).assigns.get(lineno, _NO_NAMES)


def _line_may_mutate(filename: str, lineno: int | None, name: str) -> bool:
	"""Could the statement at filename:lineno have changed `name`'s object in place?"""

	if not filename or lineno is None:
		return False

	return name in _tables(filename).mutates.get(lineno, _NO_NAMES)


def _comprehension_variables(filename: str, lineno: int | None) -> frozenset[str]:
	"""Comprehension loop variables in flight on this line, not also assigned by it"""

	if not filename or lineno is None:
		return _NO_NAMES

	tables = _tables(filename)
	names = tables.comprehension.get(lineno)

	if not names:
		return _NO_NAMES

	return names - tables.assigns.get(lineno, _NO_NAMES)


def _observed_call(filename: str | None, lineno: int | None, name: str) -> Operation | None:
	"""The call at filename:lineno that may have changed `name`'s container in place"""

	if not filename or lineno is None:
		return None

	return _tables(filename).calls.get(lineno, {}).get(name)


def _fresh_binding(filename: str | None, lineno: int | None, name: str | None = None) -> int:
	"""
	Fresh depth (see _fresh_depth_of) of the container the statement at
	filename:lineno stores, 0 when it may already exist elsewhere.
	With `name`, the statement must also be binding that plain variable
	"""

	if not filename or lineno is None:
		return 0

	entry = _tables(filename).fresh.get(lineno)

	if entry is None or (name is not None and entry[0] != name):
		return 0

	return entry[1]


def _get_call_index_in_line(frame: FrameType, target_count: int) -> int:
	"""
	Which log() call this is on the current line
	`a, b = log("x"), log("y")` -> 0 for a, 1 for b; wraps so loops restart at 0
	"""

	if target_count <= 0:
		return 0

	key = (frame.f_code.co_filename, frame.f_lineno)

	idx = _call_counter_per_line.get(key, 0)
	_call_counter_per_line[key] = (idx + 1) % target_count

	return idx % target_count


def _unpacked_name(frame: FrameType, names: tuple[str, ...]) -> str | None:
	"""The name this log() call fills in an unpacking target, blank slots aside"""

	return names[_get_call_index_in_line(frame, len(names))] or None


def _infer_name_from_frame(frame: FrameType | None, default: str | None = None) -> str | None:
	"""
	Infer the variable name, handling `x = ...` and `a, b = ..., ...`
	None (log it as a message) when the source cannot be read: the REPL, exec()
	"""

	if frame is None:
		return default

	info = _analyze_line(frame.f_code.co_filename, frame.f_lineno)

	if not info.parsed:
		return default

	if info.tuple_names:
		return _unpacked_name(frame, info.tuple_names) or default

	if info.any_single:
		return info.any_single

	# Not found, probably a `| l` statement, so not the default
	return None


def _get_constructed_target(frame: FrameType | None, callee: str) -> str | None:
	"""The variable a plain `target = callee(...)` on the frame's line assigns to"""

	if frame is None:
		return None

	info = _analyze_line(frame.f_code.co_filename, frame.f_lineno)

	return info.any_single if info.callee == callee else None


def _get_assignment_target_for_call(frame: FrameType | None) -> str | None:
	"""Which variable a log(...) call is assigned to"""

	if frame is None:
		return None

	info = _analyze_line(frame.f_code.co_filename, frame.f_lineno)

	if info.tuple_names:
		return _unpacked_name(frame, info.tuple_names) or info.log_single

	return info.log_single


__all__ = [
	"_comprehension_variables",
	"_fresh_binding",
	"_get_assignment_target_for_call",
	"_get_call_index_in_line",
	"_get_constructed_target",
	"_infer_name_from_frame",
	"_is_direct_log_call",
	"_is_user_code",
	"_line_assigns",
	"_line_may_mutate",
	"_observed_call",
]
