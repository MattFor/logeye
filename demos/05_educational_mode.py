"""
Educational mode turns a trace into a story: plain-English steps, no file names
and none of the internal noise. Made for learning and teaching algorithms.

    python demos/05_educational_mode.py
"""

from logeye import log

print("--- Bubble sort: watch the list change, swap by swap ---")


@log(mode="edu")
def bubble_sort(numbers):
	for end in range(len(numbers) - 1, 0, -1):
		for i in range(end):
			if numbers[i] > numbers[i + 1]:
				numbers[i], numbers[i + 1] = numbers[i + 1], numbers[i]
	return numbers


bubble_sort([5, 1, 4, 2])

print("\n--- Binary search: how the window narrows ---")


@log(mode="edu")
def binary_search(items, target):
	low, high = 0, len(items) - 1

	while low <= high:
		middle = (low + high) // 2

		if items[middle] == target:
			return middle

		if items[middle] < target:
			low = middle + 1
		else:
			high = middle - 1

	return -1


binary_search([1, 3, 5, 7, 9, 11], 9)

print("\n--- Radix sort: bucket by bucket, with a message after each pass ---")


@log(mode="edu")
def radix_sort(numbers):
	exp = 1

	while max(numbers) // exp > 0:
		buckets = [[] for _ in range(10)]

		for number in numbers:
			buckets[(number // exp) % 10].append(number)

		numbers = []
		for bucket in buckets:
			numbers.extend(bucket)

		# Messages inside an edu function are part of the story too
		log("After sorting on the {}s digit: $numbers", exp)
		exp *= 10

	return numbers


radix_sort([170, 45, 75, 90, 802, 24, 2, 66])
