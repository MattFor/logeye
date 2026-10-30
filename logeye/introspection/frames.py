from __future__ import annotations

import os
import sys

from types import FrameType

from .. import config

# Resolved once, recomputing per frame walk dominated _caller_frame
# normcase: Windows paths compare case-insensitively
_LIBRARY_ROOT = os.path.normcase(os.path.abspath(os.path.dirname(os.path.dirname(__file__))))
_LIBRARY_PREFIX = _LIBRARY_ROOT + os.sep

# co_filename -> part of logeye itself? Interned per code object, so stays tiny
_library_file_cache: dict[str, bool] = {}


def _is_library_file(filename: str) -> bool:
	cached = _library_file_cache.get(filename)
	if cached is not None:
		return cached

	if filename:
		resolved = os.path.normcase(os.path.abspath(filename))
		is_library = resolved == _LIBRARY_ROOT or resolved.startswith(_LIBRARY_PREFIX)
	else:
		is_library = False

	_library_file_cache[filename] = is_library
	return is_library


# The standard library; third-party code is recognised by its site-packages path.
# Not sys.prefix: projects live under it too (/usr/src/app in a Docker image)
_EXTERNAL_ROOTS = (os.path.normcase(os.path.dirname(os.path.abspath(os.__file__))) + os.sep,)

_external_file_cache: dict[str, bool] = {}


def _is_external_code(filename: str) -> bool:
	"""True for the stdlib, site-packages and frozen modules: traceable, but noise"""

	cached = _external_file_cache.get(filename)
	if cached is not None:
		return cached

	if not filename:
		is_external = True
	elif filename.startswith("<"):
		# <string>, <stdin> are user code; <frozen ...> is not
		is_external = filename.startswith("<frozen")
	else:
		resolved = os.path.normcase(os.path.abspath(filename))
		is_external = "site-packages" in resolved or "dist-packages" in resolved or resolved.startswith(_EXTERNAL_ROOTS)

	_external_file_cache[filename] = is_external
	return is_external


def _relative_path(filename: str) -> str:
	"""`filename` relative to the project root, or as is across Windows drives"""

	try:
		return os.path.relpath(filename, config._g_project_root)
	except ValueError:
		return filename


def _get_location(frame: FrameType | None) -> tuple[str | None, int | None]:
	if frame is None:
		return None, None

	return frame.f_code.co_filename, frame.f_lineno


def _caller_frame(skip_external: bool = False) -> FrameType | None:
	"""
	Walk outwards to the first frame not inside logeye itself
	`skip_external` also walks past the stdlib and site-packages, for an event loop's frames
	"""

	try:
		frame = sys._getframe(1)
	except ValueError:
		return None

	try:
		while frame is not None:
			filename = frame.f_code.co_filename

			if not _is_library_file(filename) and not (skip_external and _is_external_code(filename)):
				return frame

			frame = frame.f_back

		return None
	finally:
		del frame


__all__ = [
	"_caller_frame",
	"_get_location",
	"_is_external_code",
	"_is_library_file",
	"_relative_path",
]
