# Changelog

## [Unreleased]

### Fixed

- **`@log` no longer changes what the program computes.** Traced functions used to swap
  their locals for logging copies, so a list or dict argument changed in place never
  reached the caller (`sort_in_place(data)` left `data` unsorted), and any plain object
  local turned into a `LoggedObject`, losing its class and methods (`p.norm()` raised
  `AttributeError`, `isinstance` failed, pandas frames broke). Now only a container the
  statement itself just built (`queue = []`, `seen = set()`) is wrapped; everything else is
  left alone, and changes made to it in place are found by comparing against a snapshot.
  The same rule covers `@log` class attributes and values stored into logged containers,
  so appended or assigned objects keep their identity
- Generators: the return value reaches `yield from` again, and every `throw()` reaches
  the generator, not only the first
- `@log async def` stays a coroutine function for `inspect.iscoroutinefunction` and the
  frameworks that ask it
- Functions called inside a traced generator report their return again
- Generator yields follow educational mode
- `watch()`, `x = log(...)` or `| l` inside a `@log` function no longer stop the
  function's own tracing (its return went missing), and `watch(threshold=)` applies there
- `watch()` keeps a tracer installed before it (pdb, coverage, ...) working
- `@log` stacked above `@staticmethod` no longer passes `self` to the function
- A decorated subclass of a decorated class reports each construction and attribute once
- A `@log` class defining only `__new__` can be constructed again; one defining neither
  `__new__` nor `__init__` still rejects arguments
- A nested function's return line shows its own arguments, not the outer function's
- `account = BankAccount()` names the instance `account`, not `bankaccount`
- The first argument of a call is no longer dropped when it is a class or a logged
  instance, and methods of plain classes no longer show `self`
- The return line shows the arguments as they were passed, not as the body left them
- `log("...", value)` no longer expands `$names` found inside `value`, and a `$name`
  value is expanded once rather than twice, so logged data cannot pull in other variables
- A `repr()` that raises no longer crashes the logged program
- Educational mode no longer prints raw payload dicts for `setattr`, `update`, `clear`...
- `|=` on a logged dict is logged
- `log([...])` and `log({...})` without an assignment print the value instead of
  nothing or `set = ...`, and `log(obj)` reports a plain object instead of nothing
- Source that cannot be read (the REPL, `exec`) logs a message instead of `PLACEHOLDER = ...`
- Comprehension loop variables are no longer reported as the function's locals, and
  comprehensions are no longer traced as nested functions on Python 3.11 and older
- `$rpath` and the "project" path mode no longer crash on Windows across drives
- Code under `sys.prefix` (a Docker image's `/usr/src/app`) is no longer mistaken for
  the standard library; library paths compare case-insensitively on Windows
- Set updates from a generator log the values instead of empty lists
- `stack.pop()` is shown as `pop()`, not `pop(-1)`
- Wrapped containers no longer keep every original object alive

### Added

- Async functions and async generators are traced like any other function: locals, each
  yield and the result, across every `await`. The tracer is only installed while their body
  runs, so the event loop's other tasks are untouched. Async generators stay async generator
  functions and forward `asend`, `athrow` and `aclose`
- `heapq`, `deque` and friends: a change made around a container's logging methods (heapq
  writes to a list's storage directly) is reported, written as the call that made it:
  `heappush(queue, (1, 'B'))`, `queue.popleft() -> 'A'`. A container your function
  received reads the same way when a call changed it (`scores.sort(...)`)
- Python 3.8 and 3.9 support
- GitHub Actions: ruff, basedpyright (against 3.8) and the tests on Python 3.8 to 3.14 on
  Linux, macOS and Windows; tagged releases publish to PyPI through trusted publishing
  and create the GitHub release
- A new demo suite: ten numbered, self-contained demos with an index and `run_all.py`.
  Their output is checked in CI against `tests/demo_output/`
- Coverage in CI, failing under 90%. `LOGEYE_MEASURE_TRACERS=1` lets coverage see the code
  inside LogEye's own trace functions, which it otherwise cannot
- The version comes from the git tag; releasing is pushing `vX.Y.Z`
- `py.typed`, so type checkers use LogEye's annotations
- `CONTRIBUTING.md`, `SECURITY.md`, issue and pull request templates, dependabot

### Changed

- No more "cannot trace the body of async function" warning: the body is traced
- `release.sh` is gone: CI tests, builds, publishes to PyPI and creates the GitHub release
  from a pushed `vX.Y.Z` tag, or a release made on GitHub
- The internal module `logeye.emmiter` is now `logeye.emitter`; import `clear_log_file`
  from `logeye`
- Built with hatchling; the license is declared as an SPDX expression

## [1.6.2] - 08:34 CEST 18-08-2026

### Fixed

- logs not displaying calls properly
- =filter matched the wrong argument after 1.6.1
- _recently_emitted emitted twice

## [1.6.1] - 07:43 CEST 18-08-2026

### Fixed

- Nested assignment unpacking names every target. `(a, (b, c)) = log("x"),
(log("y"), log("z"))` reports `a`, `b` and `c` instead of calling all three
  `a`; list targets (`[a, [b, c]] = ...`) work the same way, and a target that
  is not a plain name (`obj.attr`, `items[0]`) no longer shifts the surrounding names onto the wrong values
- C decorators such as `functools.lru_cache` report their exit properly.
- Re-assigning a watched variable to an equal value is reported as a
  `(change)`. Lines that only read the name still emit nothing, and a
  configured `threshold=` suppresses zero-delta writes as before

### Performance

- `stat()` on a traced file is rate-limited rather than run per lookup which keeps the watcher's per-line cost flat

## [1.6.0] - 00:48 CEST 18-08-2026

### Performance

- Assignment-target lookup is memoised per `(file, line)` instead of
  `ast.parse`-ing the whole source file on every decorated call: 256 µs -> 2.8 µs
- Both tracers now decline frames they will never log. stdlib and
  third-party code no longer pays for a Python callback per line
- `watch()` no longer slows the rest of the process down by a lot
- File logging keeps handles open instead of reopening per line: 20.7 µs -> 1.9 µs

### Fixed

- `@log` works across modules and in threads. The tracer used to compare the
  callee's filename to the caller's and log nothing but the call
- Calling the same function twice logs its body again; baselines are no longer
  shared across invocations (which also silenced every level of a recursion)
- The last statement of a function body is logged, and line numbers point at
  the statement that produced the value
- Generators are traced (`(yield)`, with `send`/`throw`/`close` forwarded), and
  a function that raised is reported as `(raise)` rather than returning `None`
- Logging no longer changes what the program computes. `LoggedObject`
  delegates `__eq__`/`__hash__`, and modules, frames, tracebacks, exceptions and
  file objects are left unwrapped instead of being expanded into the log
- Shared references are wrapped once by identity rather than once per path, and
  cyclic structures render `"<cycle>"` instead of blowing the stack
- numpy arrays and pandas frames no longer abort the traced program with
  `ValueError: The truth value of an array ... is ambiguous`
- C callables report their result: `log(len)` and friends emit `(return)` /
  `(raise)` from the wrapper, and `log(int)` no longer raises on immutable types
- Per-call display settings are thread-local
- `set_output_formatter()` takes effect, and educational mode honours `level=`
  and `filter=`
- `@log` patches classes in place, so `type(obj) is MyClass` still holds;
  `__slots__` classes work
- A bare `log(value)` emits the value as a message instead of printing
  `None = value` or crashing in educational mode

### Added

- `stop_watching()` - removes the global tracer and restores what was there before
- `clear_log_file(*paths)` - empties log files so a rerun starts clean
- `tests/conftest.py`, plus 59 new tests covering the fixes above and
  C-implemented callables - `pytest tests/` now runs on a clean checkout

### Internal

- Everything now adheres to basedpyright
- Per-code-object watcher state is capped so long-lived processes cannot grow
  without bound
- Removed dead code from the tracer hot paths and name-inference helpers

## [1.5.2] - 00:28 CEST 15-04-2026

### Added

- **Threshold-based change filtering**

  - New `threshold` parameter for `log()` and `watch()` to control when changes are emitted
  - Supports:

    - Absolute thresholds:

      ```python
      x = log(10, threshold=5)
      ```

    - Relative thresholds:

      ```python
      x = log(100, threshold=("relative", 0.1))  # 10%
      ```

    - Combined thresholds:

      ```python
      x = log(100, threshold={"absolute": 5, "relative": 0.1})
      ```

    - Per-variable thresholds in functions:
      ```python
      @log(threshold={"x": ("relative", 0.2)})
      def f():
      	x = 10
      	x += 1  # Ignored here
      	x += 3  # Emitted normally
      ```

  - Prevents noisy logs from small fluctuations
  - Works with:

    - scalar values
    - function-local variables
    - watched variables (`watch`)
    - nested structures (e.g. `arr[0]`)

  - First assignment always emits (`(set)`), a threshold applies only to `(change)`

### Changed

- Function-level tracing now integrates threshold filtering directly (no longer depends on global watcher state)

---

## [1.5.1] - 23:09 CEST 30-03-2026

### Fixed

- _infer_name_from_frame incorrectly returning "set" as a default option when literally nothing is found,  
  instead it now returns None so that the pipe operator single messages work correctly,  
  also adjusted the default to be PLACEHOLDER and not "set" to avoid confusion
- Fixed incorrect self-referencing of basic types

### Changed

- Updated examples
- Better formatting in educational mode
- Better formatting in code

---

## [1.5.0] - 17:46 CEST 27-03-2026

### Added

- **Global variable tracking improvements**

  - `var = log(val)` now reliably registers variables for continuous tracking
  - Improved watcher integration with global trace system  
    For example:
    ```python
    x = "xyz" | l

    x = 10
    x = {"a": 1, "b": 2}
    x = "xyz"
    ```
    Completely automatically does this!
    ```commandline
    [0.000s] demo1.py:15 (set) x = 'xyz'
    [0.000s] demo1.py:18 (change) x = 10
    [0.000s] demo1.py:19 (change) x = {'a': 1, 'b': 2}
    [0.000s] demo1.py:21 (change) x = 'xyz'
    ```

- **Class instrumentation (`@log` on classes)**

  - Logs `__init__` calls with arguments
  - Tracks attribute assignments on instances
  - Supports mutation detection:

    - `(set)` for first assignment
    - `(change)` for updates

  - Attribute deletion tracking (`<deleted>`)
  - Private attributes are now logged with `<priv>` prefix  
    Automatic garbage noise differentiation between _hidden and _stdlibstuff!

- **Deep nested structure tracking**

  - Enables mutation logging like:

    - `obj.user["name"] = ...`
    - `obj.items.append(...)`

- **log and l unification**

  - Both log and l now refer to the same function
  - `log` is now the preferred function for logging
  - `l` is preferred for pipe operations

  ```python
  x = "xyz" | l  # For tracking variables
  log("X is $x")  # For manual logging
  ```

- **Full class method logging**

  - Methods inside `@log` classes are now fully traced
  - Includes:

    - method calls (`(call) obj.method`)
    - returns (`(return) obj.method -> value`)
    - internal state mutations during method execution

  - Class instances now behave like fully traceable execution scopes

- **Directional flow indicators**

  - Introduced clearer execution flow markers:

    - `->` for outputs / returns
    - `<-` (internally / structurally) for flow consistency

  - Improves readability of execution traces, especially for nested calls

- **Educational mode improvements**

  - Better alignment with real execution order:

    - `Calling -> state changes -> return`

  - More consistent variable display (`x = value`)
  - Reduced ambiguity between definition vs mutation
  - Cleaner, more predictable output for testing

### Changed

- **Stricter and expanded test suite**

  - Standardised output capturing using `capture(capsys)`
  - Introduced reusable assertion helpers across all test files

- **Educational test expectations tightened**

  - Tests now assert:

    - exact number of lines
    - exact ordering of events

  - Prevents regression via accidental extra logs

- **Formatting consistency overhaul**

  - Unified output across:
    - message logging
    - function tracing
    - object mutations
  - Reduced inconsistencies between different logging paths

### Fixed

- Nested function names appearing incorrectly (e.g. `test_x.outer.inner`)
- Duplicate function definition emissions (`Defined inner()` appearing twice)
- Missing default arguments in nested function definitions
- Incorrect ordering of:
  - `Calling inner()`
  - `Defined outer.inner(...)`
- Lambda logging inconsistencies (missing or duplicated outputs)
- Variable tracking inside nested scopes
- Attribute access issues when wrapping class instances
- Broken method calls on logged class instances (`LoggedObject` conflicts)
- Nested structure mutations not being tracked correctly
- List/dict attributes not emitting mutation events
- Recursion errors in self-referencing structures
- Mixed formatting (`{}` + `$var`) not expanding correctly
- Pipe operator edge cases and name inference issues

### Discovered Limitations

- **C-based decorators (e.g. `functools.lru_cache`)**

  - Inner execution cannot be traced due to lack of Python-level introspection

- **Nested assignment unpacking**

  - Complex patterns like:

    ```python
    (a, (b, c)) = ...
    ```

  - Only partially tracked due to Python runtime limitations (no full AST access)  
    However! I will be getting to this soon!

### Dev

- Significantly expanded test suite for edge cases and complex scenarios
- Improved internal structure for future features (method tracing, advanced introspection)
- Added multiple branches for easier separation:
  - master -> stable
  - dev -> development
  - readme-changelog -> documentation
  - feature -> feature branches
  - tests -> test coverage
  - demos -> demos and examples

### Plans

- **Repeated identical assignments edge case**

  - Intended behavior:

    ```python
    x = "a" | l
    x = "a"
    x = "a"
    ```

    should produce:

    ```
    (set) x = 'a'
    (change) x = 'a'
    (change) x = 'a'
    ```

  - Currently not fully implemented in all paths

- Upcoming feature plans are now just the sub-branches on the features/ branch.
- Standardising and improving demos and documentation

---

## [1.4.0] - 18:58 CEST 24-03-2026

### Added

- Educational mode now includes clear return output:
  - `(function) returned (value)` style formatting for better readability
- Integrated Ruff for consistent formatting and linting
- Added basedpyright for static type checking
- Introduced initial type annotations across the codebase
- Improved educational mode examples in README and demos

### Changed

- Improved consistency of call and return formatting
- Updated publishing pipeline:
  - automatic Ruff formatting
  - lint + type checks during release
- Internal refactors to support typing and future maintainability

### Fixed

- Various formatting inconsistencies between full and educational modes
- Edge cases in return logging output
- Minor issues in logging behaviour uncovered during type integration

### Developer Experience

- Added Ruff integration for standardised code style
- Added basedpyright integration for type safety
- Improved contribution workflow and code consistency

### Plans

- Multithreading support!

---

## [1.3.2] - 07:08 CEST 24-03-2026

### Added

- set_mode() for setting the mode globally (f.e to education)
- More tests for the global mode setting

### Improved

- README examples

---

## [1.3.1] - 05:33 CEST 24-03-2026

### Added

- Comprehensive README overhaul with clearer structure and examples

### Dev

- Improved release pipeline with automated versioning and GitHub releases

---

## [1.3.0] - 04:38 CEST 24-03-2026

### Added

- **Educational logging mode (`mode="edu"`)**

  - Human-readable, step-by-step output for learning and algorithm tracing
  - Function calls rendered as:

    ```
    Calling foo(1, b=2)
    ```

  - Automatic argument formatting (args + kwargs)
  - Omits empty kwargs

- **Nested function call tracing**

  - Logs calls inside functions (e.g. `outer.inner()`)

- **Context-aware logging**

  - `log()` inside decorated functions now inherits:

    - `mode`
    - `show_time`
    - `show_file`
    - `show_lineno`

### Improved

- **Output clarity in educational mode**

  - Removed internal noise (`<func ...>`, debug artefacts)
  - Simplified function names (no test/module prefixes)
  - More natural mutation messages:

    ```
    Added 5 to arr -> [1, 2, 5]
    ```

### Fixed

- Formatter crash (`UnboundLocalError: prefix`)
- Incorrect call argument display (`{'args': ..., 'kwargs': ...}`)
- Missing nested call events due to tracer scope issues

### Tests

- Added educational mode test coverage:

  - Call formatting
  - Argument rendering
  - Nested function tracing
  - Inherited logging behavior
  - Human-readable mutations
  - Output cleanliness

---

## [1.2.0] - 20:58 CEST 23-03-2026

### Added

- `@log(level=...)` for verbosity control (`call`, `state`, `full`)
- `@log(filter=[...])` to log only selected variables
- Per-function file logging via `@log(filepath=...)`
- Global file logging support
- Decorator-only logging mode toggle

### Improved

- Overall logging flexibility and usability
- Reduced noise in complex traces

---

## [1.1.5] - 16:15 CEST 23-03-2026

### Changed

- Updated README documentation

---

## [1.1.4] - 16:13 CEST 23-03-2026

### Fixed

- Class wrapping issues

---

## [1.1.3] - 14:45 CEST 23-03-2026

### Fixed

- Wrapped object representation

---

## [1.1.2] - 14:14 CEST 23-03-2026

### Fixed

- Incorrect wrapping of callables

---

## [1.1.1] - 14:10 CEST 23-03-2026

### Fixed

- Mutation tracking issues
- Nested path logging bugs
- Test failures

---

## [1.1.0] - 13:49 CEST 23-03-2026

### Added

- Mutation logging support for tracked objects

### Improved

- Core logging capabilities

---

## [1.0.0] - 23-03-2026

### Added

- Initial release
- Variable logging with name inference
- Function tracing
- Object and mapping tracking
- Message logging system
- Basic test suite

[1.6.2]: https://github.com/MattFor/logeye/releases/tag/v1.6.2
[1.6.1]: https://github.com/MattFor/logeye/releases/tag/v1.6.1
[1.6.0]: https://github.com/MattFor/logeye/releases/tag/v1.6.0
[1.5.2]: https://github.com/MattFor/logeye/releases/tag/v1.5.2
[1.5.1]: https://github.com/MattFor/logeye/releases/tag/v1.5.1
[1.5.0]: https://github.com/MattFor/logeye/releases/tag/v1.5.0
[1.4.0]: https://github.com/MattFor/logeye/releases/tag/v1.4.0
[1.3.2]: https://github.com/MattFor/logeye/releases/tag/v1.3.2
[1.3.1]: https://github.com/MattFor/logeye/releases/tag/v1.3.1
[1.3.0]: https://github.com/MattFor/logeye/releases/tag/v1.3.0
[1.2.0]: https://github.com/MattFor/logeye/releases/tag/v1.2.0
[1.1.5]: https://github.com/MattFor/logeye/releases/tag/v1.1.5
[1.1.4]: https://github.com/MattFor/logeye/releases/tag/v1.1.4
[1.1.3]: https://github.com/MattFor/logeye/releases/tag/v1.1.3
[1.1.2]: https://github.com/MattFor/logeye/releases/tag/v1.1.2
[1.1.1]: https://github.com/MattFor/logeye/releases/tag/v1.1.1
[1.1.0]: https://github.com/MattFor/logeye/releases/tag/v1.1.0
[1.0.0]: https://github.com/MattFor/logeye/releases/tag/v1.0.0
