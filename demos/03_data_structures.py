"""
Lists, dicts and sets: every change is reported, and logging never changes what
the program computes. A list sorted in place is still sorted for the caller.

    python demos/03_data_structures.py
"""

from logeye import log

print("--- Containers built inside a traced function report each operation ---")


@log
def plan_route():
	stops = []
	stops.append("Paris")
	stops.append("Rome")
	stops.insert(0, "London")
	visited = set()
	visited.add(stops.pop(0))
	fares = {}
	fares["Paris"] = 120
	fares["Paris"] -= 20
	return stops


plan_route()

print("\n--- An argument changed in place: the caller sees the change ---")


@log
def grade(scores):
	for i in range(len(scores)):
		scores[i] = round(scores[i] / 10)
	scores.sort()


marks = [72, 95, 58]
grade(marks)
print("the caller's list afterwards:", marks)

print("\n--- Logging a container directly ---")

inventory = log({"apples": 3, "pears": 1})
inventory.apples = 5  # a logged dict also takes attribute access
inventory["pears"] -= 1
inventory["plums"] = 7

stack = log([])
stack.append("first")
stack.append("second")
stack.pop()

print("\n--- Nested structures report the full path ---")

game = log({"player": {"hp": 100, "items": []}})
game.player.hp -= 25
game.player["items"].append("sword")
