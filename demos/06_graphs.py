"""
Graph algorithms: Dijkstra's shortest paths with a heapq priority queue, traced in
full detail (narrowed with filter=) and then told as a story in educational mode,
and a breadth-first search over a deque.

    python demos/06_graphs.py
"""

import heapq

from collections import deque

from logeye import log

GRAPH = {
	"A": {"B": 1, "C": 4},
	"B": {"C": 2, "D": 5},
	"C": {"D": 1},
	"D": {},
}


def dijkstra(graph, start):
	distances = {vertex: float("inf") for vertex in graph}
	distances[start] = 0

	visited = set()
	queue = [(0, start)]

	while queue:
		# heapq rearranges the list behind its back; LogEye still sees every step
		distance, node = heapq.heappop(queue)

		if node in visited:
			continue

		visited.add(node)

		for neighbour, weight in graph[node].items():
			candidate = distance + weight

			if candidate < distances[neighbour]:
				distances[neighbour] = candidate
				heapq.heappush(queue, (candidate, neighbour))

	return distances


print("--- Full trace, narrowed to the two structures that matter ---")
log(dijkstra, filter=["distances", "queue"])(GRAPH, "A")

print("\n--- Educational mode ---")
log(dijkstra, mode="edu")(GRAPH, "A")

print("\n--- Breadth-first search with a deque ---")


@log(mode="edu")
def breadth_first(graph, start):
	order = []
	frontier = deque([start])
	seen = {start}

	while frontier:
		node = frontier.popleft()
		order.append(node)

		for neighbour in graph[node]:
			if neighbour not in seen:
				seen.add(neighbour)
				frontier.append(neighbour)

	return order


breadth_first(GRAPH, "A")
