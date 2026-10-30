"""
Too much output? Narrow it down with level=, filter= and threshold=.

    python demos/08_filtering.py
"""

from logeye import log


def simulate(steps):
	position = 0.0
	velocity = 10.0
	fuel = 100

	for _ in range(steps):
		velocity += 0.5
		position += velocity
		fuel -= 3

	return round(position, 1)


print("--- level='call': only calls and returns ---")
log(simulate, level="call")(3)

print("\n--- level='state': no call lines, just what changes and the result ---")
log(simulate, level="state")(1)

print("\n--- filter=: only the variables named ---")
log(simulate, filter=["fuel"])(3)

print("\n--- threshold=: only changes big enough to matter ---")
# Velocity only when it moved by 10% since it was last shown, fuel by 5 units
log(simulate, threshold={"velocity": ("relative", 0.1), "fuel": ("absolute", 5)})(4)

print("\n--- A threshold works on logged values outside functions too ---")
temperature = log(20.0, threshold=("absolute", 1))
temperature += 0.5  # too small, not shown
temperature += 0.25  # still within a degree of 20.0, the last value shown
temperature += 0.25  # 21.0 is a whole degree away: shown
