import sys
import contextlib

from typing import TYPE_CHECKING

if TYPE_CHECKING:
	from typing_extensions import override
elif sys.version_info >= (3, 12):
	from typing import override  # pyright: ignore[reportUnreachable]
else:  # pragma: no cover - measured on 3.12+, this runs on 3.8 to 3.11
	from typing import TypeVar  # pyright: ignore[reportUnreachable]

	_F = TypeVar("_F")

	def override(method: _F, /) -> _F:
		"""Backport of typing.override marks only the method"""

		# Not every callable accepts attributes
		with contextlib.suppress(AttributeError, TypeError):
			method.__override__ = True

		return method


__all__ = ["override"]
