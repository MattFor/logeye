"""Coroutines and async generators: traced bodies, every protocol call forwarded"""

import sys
import asyncio
import inspect

import pytest

from helpers import capture, assert_has, assert_not_has

from logeye import log


def test_concurrent_tasks_each_report_their_own_locals(capsys):
	@log
	async def worker(label, steps):
		count = 0
		for _ in range(steps):
			count += 1
			await asyncio.sleep(0)
		return label

	async def main():
		return await asyncio.gather(worker("a", 2), worker("b", 3))

	assert asyncio.run(main()) == ["a", "b"]

	raw, _ = capture(capsys)

	assert_has(raw, "worker.count = 2")
	assert_has(raw, "worker#2.count = 3")
	assert_not_has(raw, "worker.count = 3")


def test_tracing_is_off_while_a_coroutine_is_suspended():
	seen = []

	@log
	async def waiter(event):
		await event.wait()
		return 1

	async def main():
		event = asyncio.Event()
		task = asyncio.ensure_future(waiter(event))
		await asyncio.sleep(0)

		# The waiter is suspended: nothing of it may be installed here
		seen.append(sys.gettrace())

		event.set()
		return await task

	before = sys.gettrace()

	assert asyncio.run(main()) == 1
	assert seen == [before]


def test_exception_in_a_coroutine_is_reported_once(capsys):
	@log
	async def fail():
		await asyncio.sleep(0)
		raise ValueError("boom")

	with pytest.raises(ValueError):
		asyncio.run(fail())

	raw, ls = capture(capsys)

	assert sum("(raise)" in line for line in ls) == 1, raw
	assert_has(raw, "ValueError: boom")


def test_async_generator_is_one_and_reports_each_yield(capsys):
	@log
	async def countdown(n):
		while n > 0:
			yield n
			n -= 1

	async def collect():
		return [value async for value in countdown(3)]

	assert inspect.isasyncgenfunction(countdown)
	assert asyncio.run(collect()) == [3, 2, 1]

	raw, _ = capture(capsys)

	assert_has(raw, "(yield) countdown args=(3) -> 3")
	assert_has(raw, "(yield) countdown args=(3) -> 1")
	assert_has(raw, "(return) countdown args=(3) -> None")


def test_async_generator_forwards_asend_athrow_and_aclose():
	cleaned = []

	@log
	async def echo():
		try:
			received = None
			while True:
				try:
					received = yield received
				except ValueError:
					received = "recovered"
		finally:
			cleaned.append(True)

	async def drive():
		generator = echo()
		first = await generator.asend(None)
		echoed = await generator.asend("ping")
		recovered = await generator.athrow(ValueError())
		await generator.aclose()
		return first, echoed, recovered

	assert asyncio.run(drive()) == (None, "ping", "recovered")
	assert cleaned == [True]


def test_async_generator_with_logging_off_still_forwards_asend():
	from logeye import toggle_logs

	@log
	async def echo():
		received = yield "ready"
		yield received

	async def drive():
		generator = echo()
		ready = await generator.asend(None)
		echoed = await generator.asend("value")
		return ready, echoed

	toggle_logs(False)
	try:
		assert asyncio.run(drive()) == ("ready", "value")
	finally:
		toggle_logs(True)


def test_coroutine_awaited_inside_is_left_to_its_own_decorator(capsys):
	async def helper():
		inner = 1
		await asyncio.sleep(0)
		return inner

	@log
	async def outer():
		result = await helper()
		return result

	assert asyncio.run(outer()) == 1

	raw, _ = capture(capsys)

	assert_has(raw, "outer.result = 1")
	assert_not_has(raw, "helper")
