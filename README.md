# LogEye

[![CI](https://github.com/MattFor/logeye/actions/workflows/ci.yml/badge.svg)](https://github.com/MattFor/logeye/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/logeye)](https://pypi.org/project/logeye/)
[![Python](https://img.shields.io/pypi/pyversions/logeye)](https://pypi.org/project/logeye/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**Understand exactly what your code is doing in real time, no debugger needed.**

LogEye is a frictionless runtime logger for Python that shows variable changes, function calls, and data mutations as
they happen.

**Think of it as "print debugging" just better - automated, structured, easy to drop into, and remove from any codebase**

## Installation

```bash
pip install logeye
```

No dependencies, Python 3.8 to 3.14, any operating system.

## Quick example

```python
from logeye import log


@log
def add(a, b):
	return a + b


add(2, 3)


@log(mode="edu")
def add_edu(a, b):
	return a + b


add_edu(2, 3)
```

Output:

```commandline
[0.004s] example.py:9 (call) add args=(2, 3)
[0.004s] example.py:4 (set) add.a = 2
[0.004s] example.py:4 (set) add.b = 3
[0.004s] example.py:6 (return) add args=(2, 3) -> 5
[0.004s] Calling add_edu(2, 3)
[0.004s] Defined add_edu.a = 2
[0.004s] Defined add_edu.b = 3
[0.004s] add_edu(2, 3) returned 5
```

# Table of Contents

- [Who is it for?](#who-is-it-for)
- [What does it do?](#what-does-it-do)
  - [What exactly does it track?](#what-exactly-does-it-track)
  - [It never changes what your program does](#it-never-changes-what-your-program-does)
- [Quick start](#quick-start)
- [Educational Mode](#educational-mode)
  - [Before vs After](#before-vs-after)
  - [What changes in educational mode](#what-changes-in-educational-mode)
  - [Example - Educational Factorial](#example---educational-factorial)
- [Logging functions](#logging-functions)
- [Advanced function logging](#advanced-function-logging)
- [Logging objects](#logging-objects)
- [Messages](#messages)
- [Utility functions](#utility-functions)
- [Output format](#output-format)
- [Demos](#demos)
- [Inspiration](#inspiration)
- [Limitations](#limitations)
- [Contributing](#contributing)
- [Contact](#contact)
- [License](#license)

## Who is it for?

LogEye helps you see how your code executes step by step.

Perfect for:

- beginners learning programming
- students studying algorithms
- teachers explaining concepts

No more scattered `print()` calls. No debugger setup. Simply run your code and see everything.

Why keep doing this?

```python
print(x)
print(y)
print(queue)
```

When a single `@log` suffices?

```commandline
Popped (0, 'A') from queue
Pushed (1, 'B') onto queue
Pushed (4, 'C') onto queue
```

## What does it do?

Core features:

- educational mode for algorithm tracing
- log values with automatic variable name inference
- trace function calls, local variables, and returns
- track object and data structure mutations in real time
- format messages using f-string, template, or scope variables

Advanced features:

- filter variables and control verbosity (`level`, `filter`, `threshold`)
- log to files or stdout
- recursively track nested structures
- AST-based name inference (including multi-line assignments)

However, keep in mind that name inference is best-effort and may not be accurate in some more extreme cases.

### What exactly does it track?

Without changing your code, LogEye shows:

- function calls and returns
- local variables inside functions
- object attribute changes
- list / dict / set / deque mutations, `heapq` operations included
- nested structures
- recursion and call depth
- generators, exceptions, builtins, async functions and async generators

### It never changes what your program does

LogEye only watches. A list your function sorts in place is still sorted for the caller, an object keeps its class and
its methods, and two names for the same list stay two names for the same list:

```python
from logeye import log


@log
def sort_scores(scores):
	scores.sort(reverse=True)


results = [72, 95, 58]
sort_scores(results)
print(results)
```

```commandline
[0.003s] example.py:10 (call) sort_scores args=([72, 95, 58])
[0.004s] example.py:4 (set) sort_scores.scores = [72, 95, 58]
[0.004s] example.py:6 (change) sort_scores.scores.sort(...) -> [95, 72, 58]
[0.004s] example.py:6 (return) sort_scores args=([72, 95, 58]) -> None
[95, 72, 58]
```

## Quick start

```python
from logeye import log

x = log(10)
message = log("Hello from {name}", name="Matt")


@log(level="call")
def add(a, b):
	something = 2 + 2  # Unused
	return a + b


add(2, 2)

name = "Matt"
message2 = log("Hello from $name")

config = log({"debug": True, "port": 8080})
config.port = 9090
config["debug"] = False
```

Example output:

```commandline
[0.003s] example.py:3 (set) x = 10
[0.004s] example.py:4 (set) message = 'Hello from Matt'
[0.004s] example.py:13 (call) add args=(2, 2)
[0.004s] example.py:10 (return) add args=(2, 2) -> 4
[0.005s] example.py:16 (set) message2 = 'Hello from Matt'
[0.005s] example.py:18 (set) config = {'debug': True, 'port': 8080}
[0.005s] example.py:19 (change) config.port = 9090
[0.005s] example.py:20 (change) config.debug = False
```

# Educational Mode!

Educational mode is designed to make algorithms read like a story instead of a trace. :)

Instead of raw internal logs, it shows:

- clean function calls
- meaningful variable changes
- human-readable operations
- minimal noise

Enable it with:

```python
from logeye import log, set_mode

# Globally
set_mode("edu")


# Locally
@log(mode="edu")
def my_function(): ...
```

## Before vs After

The same Dijkstra run, with a `heapq` priority queue, from [demos/06_graphs.py](demos/06_graphs.py).

### Default mode

Narrowed with `filter=["distances", "queue"]`:

```text
(set) dijkstra.distances = {'A': inf, 'B': inf, 'C': inf, 'D': inf}
(change) dijkstra.distances.A = 0
(set) dijkstra.queue = [(0, 'A')]
(change) heappop(dijkstra.queue) -> (0, 'A') | []
(change) dijkstra.distances.B = 1
(change) heappush(dijkstra.queue, (1, 'B')) -> [(1, 'B')]
(change) dijkstra.distances.C = 4
(change) heappush(dijkstra.queue, (4, 'C')) -> [(1, 'B'), (4, 'C')]
(change) heappop(dijkstra.queue) -> (1, 'B') | [(4, 'C')]
(change) dijkstra.distances.C = 3
(change) heappush(dijkstra.queue, (3, 'C')) -> [(3, 'C'), (4, 'C')]
...
```

---

### Educational mode

```text
Calling dijkstra({'A': {'B': 1, 'C': 4}, 'B': {'C': 2, 'D': 5}, 'C': {'D': 1}, 'D': {}}, 'A')
Defined dijkstra.graph = {'A': {'B': 1, 'C': 4}, 'B': {'C': 2, 'D': 5}, 'C': {'D': 1}, 'D': {}}
Defined dijkstra.start = 'A'
Defined dijkstra.distances = {'A': inf, 'B': inf, 'C': inf, 'D': inf}
Set dijkstra.distances.A = 0
Defined dijkstra.visited = set()
Defined dijkstra.queue = [(0, 'A')]
Popped (0, 'A') from queue
Defined dijkstra.distance = 0
Defined dijkstra.node = 'A'
Added A to visited
...
Set dijkstra.distances.B = 1
Pushed (1, 'B') onto queue
...
dijkstra({'A': {'B': 1, 'C': 4}, 'B': {'C': 2, 'D': 5}, 'C': {'D': 1}, 'D': {}}, 'A') returned {'A': 0, 'B': 1, 'C': 3, 'D': 4}
```

## What changes in educational mode

- Function calls become readable:

  ```text
  Calling foo(1, b=2)
  ```

- No raw `args/kwargs` dictionaries

- Internal noise is removed:

  - no `<func ...>`
  - no test/module prefixes
  - no file names or line numbers

- Data structure operations are human-friendly:

  ```text
  Added 5 to the end of arr
  ```

## Example - Educational Factorial

```python
from logeye import log, l

l("FACTORIAL")


@log(mode="edu")
def factorial(n):
	if n == 1:
		return 1
	return n * factorial(n - 1)


factorial(5)
```

Output:

```text
[0.003s] example.py:3 FACTORIAL
[0.004s] Calling factorial(5)
[0.004s] Defined factorial.n = 5
[0.004s] Calling factorial#2(4)
[0.004s] Defined factorial#2.n = 4
[0.004s] Calling factorial#3(3)
[0.004s] Defined factorial#3.n = 3
[0.004s] Calling factorial#4(2)
[0.004s] Defined factorial#4.n = 2
[0.004s] Calling factorial#5(1)
[0.004s] Defined factorial#5.n = 1
[0.004s] factorial#5(1) returned 1
[0.004s] factorial#4(2) returned 2
[0.004s] factorial#3(3) returned 6
[0.004s] factorial#2(4) returned 24
[0.004s] factorial(5) returned 120
```

It’s especially useful for:

- learning recursion
- understanding sorting algorithms
- teaching data structures
- quickly verifying logic without a debugger

[demos/05_educational_mode.py](demos/05_educational_mode.py) walks through bubble sort, binary search and radix sort.

## Logging functions

Decorate a function or wrap it with `log`:

```python
from logeye import log


@log
def add(a, b):
	total = a + b
	return total


add(2, 3)
```

```commandline
[0.004s] example.py:10 (call) add args=(2, 3)
[0.004s] example.py:4 (set) add.a = 2
[0.004s] example.py:4 (set) add.b = 3
[0.004s] example.py:6 (set) add.total = 5
[0.004s] example.py:7 (return) add args=(2, 3) -> 5
```

This will log:

- the function call
- local variable changes inside the function
- the return value

Recursion, nested functions, generators, exceptions, methods, builtins (`log(len)`), async functions and async
generators are covered too, see [demos/02_functions.py](demos/02_functions.py) and [demos/10_native_and_async.py](demos/10_native_and_async.py).

## Advanced function logging

You can customise how functions are logged using `@log(...)`:

### Control verbosity

```python
from logeye import log


@log(level="call")
def foo():
	x = 10
	return x
```

#### Levels:

- "call" - only function calls and returns
- "state" - no call lines, just variable changes and the result
- "full" - full tracing (default)

```python
from logeye import log


@log(filter=["x"])
def foo():
	x = 10
	y = 20
	return x + y
```

Only selected variables will be logged.

```python
from logeye import log


@log(threshold={"velocity": ("relative", 0.1), "hp": ("absolute", 5)})
def tick():
	velocity = 10.0
	hp = 100
	...
```

Small numeric changes are skipped until they add up to the threshold. A threshold can be a number (absolute), an
`("absolute" | "relative", value)` tuple, or a mapping from variable name to either.

```python
from logeye import log


@log(filepath="logs/my_func.log")
def foo():
	x = 10
	return x
```

Logs for this function will be written to a file instead of stdout.

### Combos

```python
from logeye import log


@log(level="state", filter=["queue"], filepath="queue.log")
def process():
	queue = []
	queue.append(1)
	queue.append(2)
```

[demos/08_filtering.py](demos/08_filtering.py) shows each option on the same function.

## Logging objects

`log()` wraps a mapping into a logged object you can also use with attribute access:

```python
from logeye import log

settings = log({"theme": "dark", "volume": 3})
settings.theme = "light"
settings.volume += 1
```

Decorate a class with `@log` to see every instance being built and changed:

```python
from logeye import log


@log
class User:
	def __init__(self):
		self.name = "Matt"
		self.active = True


user = User()
user.name = "For"
```

```commandline
[0.003s] example.py:3 (set) settings = {'theme': 'dark', 'volume': 3}
[0.003s] example.py:4 (change) settings.theme = 'light'
[0.003s] example.py:5 (change) settings.volume = 4
[0.003s] example.py:15 (call) user <- User.__init__
[0.003s] example.py:11 (set) user.name = 'Matt'
[0.003s] example.py:12 (set) user.active = True
[0.003s] example.py:16 (change) user.name = 'For'
```

Instances stay real instances: `type(user) is User` still holds. See [demos/04_classes.py](demos/04_classes.py).

## Messages

Use `log()` with a string to emit a formatted message:

```python
from logeye import log

name = "Matt"
email = "mattfor@relaxy.xyz"
log("Current user: $name, email: $email")

# Also works like this!
log("Current user: {}, email: {}", "Matt", "mattfor@relaxy.xyz")
```

```commandline
[0.003s] example.py:5 Current user: Matt, email: mattfor@relaxy.xyz
[0.004s] example.py:8 Current user: Matt, email: mattfor@relaxy.xyz
```

`$name` placeholders come from the caller's scope, `{}` placeholders from the arguments. `$fpath`, `$rpath` and
`$apath` give the current file's name, relative path and absolute path. Only the template is expanded: a value that
happens to contain `$something` or `{}` is printed as is.

## Utility functions

### `watch(value, name=None)`

Logs a value without wrapping or changing it, then keeps reporting the variable it was assigned to.

### `toggle_logs(True/False)`

Disable or enable logging globally.

### `set_path_mode(mode)`

Controls how file paths are shown in output.

Accepted values:

- `absolute`
- `project`
- `file`

### `set_output_formatter(func)`

Replace the default formatter.

Signature:

```python
func(elapsed, kind, name, value, filename, lineno)
```

The formatter may take fewer positional arguments (`func(elapsed, kind, name, value)`), and returning `None` drops the
line.

### `reset_output_formatter()`

Restore the built-in formatter.

### `stop_watching()`

Remove the line tracer `watch()` installs, restoring whatever tracer was there before.

## Output format

By default, messages look like this:  
(note, the path by default is relative to the run directory of the file you're launching the module in)

```commandline
[0.123s] path/to/file.py:42 (set) x = 10
```

For plain messages:

```commandline
[0.123s] path/to/file.py:42 some text
```

### File logging

```python
from logeye import set_global_log_file, toggle_global_log_file

set_global_log_file("logs/app.log")
toggle_global_log_file(True)
```

All logs will now be written to the specified file.
To disable: `toggle_global_log_file(False)`

## Demos

[demos/](demos/) is a guided tour, one topic per file, from a one-minute quick start to educational mode, classes,
filtering, file output and async functions. Run one, or all of them:

```bash
python demos/01_quickstart.py
python demos/run_all.py
```

Every demo's exact output is checked in CI and kept in [tests/demo_output/](tests/demo_output/), so you can read what
each one prints without running it.

# Inspiration

Idea came to be during Warsaw IT Days 2026. During the Python lecture "Logging module adventures".  
I thought there definitely was an easier way to do it without repeating yourself constantly, and it turns out there was!

## Limitations

- variable name inference is **best-effort** and may fail in complex or highly dynamic expressions
- some edge cases (e.g. deeply nested calls, chained expressions, unusual syntax) may fall back to a generic name or
  plain message
- lambda functions are **not automatically traced** unless explicitly wrapped with `log()`
- function tracing relies on `sys.settrace()` and may introduce overhead in performance-sensitive code
- debuggers and coverage tools use `sys.settrace()` too: stepping through a `@log` function with pdb, or measuring its
  coverage, does not work while it runs
- a coroutine awaited inside a logged one is traced only when it is logged itself
- a change to a container that no call on its line explains, such as `arr[i] = x` on a list your function received or
  a change made inside another function, is reported as the container's new value; calls like `arr.sort()` or
  `heapq.heappush(arr, x)` are always named
- `log(container)` returns a logging copy: keep using the returned value, not the original
- logging inside heavily recursive or multithreaded code may produce noisy or hard-to-follow output
- AST-based analysis requires access to source files and may not work correctly in environments without source code (
  e.g. compiled/obfuscated code, some REPLs)
- tuple assignment tracking depends on call order and may behave unexpectedly in complex expressions
- logging output is intended for debugging and introspection, not structured logging or production telemetry

## Contributing

Bug reports, ideas and pull requests are welcome. [CONTRIBUTING.md](CONTRIBUTING.md) covers the setup, the checks CI
runs, and how releases are made.

## Contact

If you have questions, ideas, or run into issues:

- please open an issue!
- or email me mattfor@relaxy.xyz
- or add me on discord @mattfor

## Notable contributors

- @OutSquareCapital Helped with typing and refactoring

## License

MIT, see [LICENSE](LICENSE). By [MattFor](https://github.com/MattFor).
