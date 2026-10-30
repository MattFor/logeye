"""
LogEye in one minute: log a value, a message and a whole function.

    python demos/01_quickstart.py
"""

from logeye import l, log

# A value is logged under the name it is assigned to, and handed back unchanged
x = log(10)

# The pipe form does the same, read left to right
y = 20 | l

# Messages take {} arguments, or $variables straight from the scope
log("x + y = {}", x + y)
log("x is $x and y is $y")


# A function: every call, every local variable and the return value
@log
def add(a, b):
	total = a + b
	return total


add(2, 3)

# Logged names stay watched, so later changes show up too
x = 15
