# LogEye demos

A guided tour of LogEye, one topic per file. Each demo is self-contained and
explains itself in its docstring; read the code, then run it and compare.

| Demo                                             | What it shows                                                                                      |
| ------------------------------------------------ | -------------------------------------------------------------------------------------------------- |
| [01_quickstart.py](01_quickstart.py)             | Logging a value, a message and a function in a few lines                                           |
| [02_functions.py](02_functions.py)               | `@log` on functions: locals, returns, recursion, nested functions, generators, exceptions          |
| [03_data_structures.py](03_data_structures.py)   | List / dict / set changes, and why logging never changes what your program computes                |
| [04_classes.py](04_classes.py)                   | `@log` on a class: construction, attribute changes, methods, class and static methods              |
| [05_educational_mode.py](05_educational_mode.py) | Educational mode: bubble sort, binary search and radix sort told step by step                      |
| [06_graphs.py](06_graphs.py)                     | Dijkstra with a `heapq` priority queue, in two views, and a breadth-first search over a `deque`    |
| [07_messages.py](07_messages.py)                 | `log("...")` as a better `print()`: `{}` placeholders, `$variables`, file paths                    |
| [08_filtering.py](08_filtering.py)               | Cutting the noise with `level=`, `filter=` and `threshold=`                                        |
| [09_output.py](09_output.py)                     | Log files, a custom formatter, path modes, switching logging off                                   |
| [10_native_and_async.py](10_native_and_async.py) | Builtins, C functions, `functools.partial`, callable objects, async functions and async generators |

## Running them

From a checkout, with LogEye installed (`pip install -e .` or `uv sync`):

```bash
python demos/01_quickstart.py
```

Or every demo in order, no installation needed:

```bash
python demos/run_all.py
```

`09_output.py` writes its log files to `demos/output/`, which git ignores.
