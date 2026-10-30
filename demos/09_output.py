"""
Where the output goes and what it looks like: log files, a custom formatter,
path modes, and switching logging off.

    python demos/09_output.py
"""

import os

from logeye import (
	clear_log_file,
	log,
	reset_output_formatter,
	set_global_log_file,
	set_output_formatter,
	set_path_mode,
	toggle_global_log_file,
	toggle_logs,
)

# Written next to this file; demos/output/ is ignored by git
OUTPUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
FUNCTION_LOG = os.path.join(OUTPUT, "checkout.log")
GLOBAL_LOG = os.path.join(OUTPUT, "everything.log")

clear_log_file(FUNCTION_LOG, GLOBAL_LOG)

print("--- One function's trace to its own file ---")


@log(filepath=FUNCTION_LOG)
def checkout(prices):
	total = sum(prices)
	discount = total * 0.1 if total > 100 else 0
	return total - discount


checkout([40, 80])
print("(written to demos/output/checkout.log)")

print("\n--- Everything to one file ---")
set_global_log_file(GLOBAL_LOG)
toggle_global_log_file(True)

order_id = log(1042)
log("Order $order_id received")

toggle_global_log_file(False)
print("(written to demos/output/everything.log)")

print("\n--- A custom formatter ---")


def compact(elapsed, kind, name, value):
	return f"{kind.upper():<7}| {name} -> {value!r}"


set_output_formatter(compact)
answer = log(42)
log("formatted by compact()")
reset_output_formatter()

print("\n--- Path modes: file (the default), project, absolute ---")
set_path_mode("project")
log("the path is relative to the working directory")
set_path_mode("file")
log("and back to just the file name")

print("\n--- Logging off and on again ---")
toggle_logs(False)
log("this line is never shown")
toggle_logs(True)
log("logging is back")

print("\n--- What the files received ---")
for path in (FUNCTION_LOG, GLOBAL_LOG):
	print(f"{os.path.basename(path)}:")
	with open(path, encoding="utf-8") as handle:
		print("".join(f"    {line}" for line in handle))
