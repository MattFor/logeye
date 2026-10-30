"""
Callables without Python source (builtins, C functions, functools.partial and
callable objects) report their call and result. Async functions and async
generators are traced like any other function, across every await.

    python demos/10_native_and_async.py
"""

import asyncio
import functools
import inspect
import math
import warnings

from logeye import log

print("--- Builtins and C functions ---")
length = log(len)
length([1, 2, 3])

root = log(math.sqrt)
root(144)

print("\n--- A builtin that raises ---")
price_of = log({"tea": 3.5}.__getitem__)
try:
	price_of("coffee")
except KeyError:
	print("...the KeyError reaches the caller unchanged")

print("\n--- functools.partial and callable objects ---")
at_least_ten = log(functools.partial(max, 10))
at_least_ten(4)


class Doubler:
	def __call__(self, value):
		return value * 2


double = log(Doubler())
double(21)

print("\n--- C types cannot be patched, so they come back unchanged ---")
with warnings.catch_warnings(record=True) as caught:
	warnings.simplefilter("always")
	same = log(int)

print(f"warning: {caught[0].message}")
print(f"log(int) is int: {same is int}")

print("\n--- Async functions: traced across every await ---")


@log
async def fetch_price(item):
	await asyncio.sleep(0)
	price = {"tea": 3.5, "cake": 4.0}[item]
	return price


# Still a coroutine function to asyncio and to every framework that checks
print("iscoroutinefunction:", inspect.iscoroutinefunction(fetch_price))


@log
async def receipt(items):
	for item in items:
		yield item, await fetch_price(item)


async def main():
	await fetch_price("tea")

	print("\n--- Async generators: every value yielded ---")
	async for _ in receipt(["tea", "cake"]):
		pass


asyncio.run(main())
