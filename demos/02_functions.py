"""
@log on a function: its calls, arguments, local variables and return value,
plus recursion, nested functions, generators and exceptions.

    python demos/02_functions.py
"""

from logeye import log

print("--- Every local variable, as it changes ---")


@log
def total(a, b):
	result = a + b
	result = result * 2
	result = result + 5
	return result


total(3, 4)

print("\n--- Recursion: each level gets its own number ---")


@log
def factorial(n):
	if n <= 1:
		return 1
	return n * factorial(n - 1)


factorial(4)

print("\n--- Functions defined inside are traced as well ---")


@log
def hypotenuse(a, b):
	def square(v):
		return v * v

	return (square(a) + square(b)) ** 0.5


hypotenuse(3, 4)

print("\n--- Generators: every value yielded, and the final return ---")


@log
def countdown(n):
	while n > 0:
		yield n
		n -= 1
	return "liftoff"


for _ in countdown(3):
	pass

print("\n--- An exception is reported where it leaves the function ---")


@log
def parse_age(text):
	age = int(text)
	return age


try:
	parse_age("forty")
except ValueError:
	print("...and the ValueError still reaches the caller")
