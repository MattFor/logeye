"""
@log on a class: construction, every attribute change and every method call,
while instances stay genuine instances of the class.

    python demos/04_classes.py
"""

from logeye import log


@log
class BankAccount:
	def __init__(self, owner, balance=0):
		self.owner = owner
		self.balance = balance
		self.history = []

	def deposit(self, amount):
		self.balance += amount
		self.history.append(("deposit", amount))
		return self.balance

	def withdraw(self, amount):
		if amount > self.balance:
			raise ValueError("insufficient funds")
		self.balance -= amount
		self.history.append(("withdraw", amount))
		return self.balance

	@classmethod
	def with_bonus(cls, owner):
		return cls(owner, balance=10)

	@staticmethod
	def fee(amount):
		return round(amount * 0.01, 2)

	def __repr__(self):
		return f"BankAccount({self.owner!r}, balance={self.balance})"


print("--- Construction ---")
account = BankAccount("Ada", balance=100)

print("\n--- Methods, and the attribute changes they make ---")
account.deposit(50)
account.withdraw(30)

print("\n--- Attributes changed from outside are reported too ---")
account.owner = "Ada Lovelace"

print("\n--- Class methods and static methods ---")
bonus = BankAccount.with_bonus("Grace")
BankAccount.fee(250)

print("\n--- A failing call is reported, then raises as usual ---")
try:
	account.withdraw(1_000)
except ValueError as error:
	print(f"...caught: {error}")

print("\n--- Still a real BankAccount ---")
print("type(account) is BankAccount:", type(account) is BankAccount)
