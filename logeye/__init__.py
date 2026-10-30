from .core import watch, _LogAPI
from .emitter import clear_log_file
from .watcher import _uninstall_global_trace as stop_watching
from .formatting import set_output_formatter, reset_output_formatter

from .config import (
	toggle_logs,
	toggle_decorator_log_only,
	toggle_message_metadata,
	toggle_global_log_file,
	set_mode,
	set_path_mode,
	set_global_log_file,
)

log = _LogAPI()
l = log  # noqa: E741
w = watch

# The "[0.000s]" origin is config._g_start_time, set at import

__all__ = [
	"clear_log_file",
	"l",
	"log",
	"reset_output_formatter",
	"set_global_log_file",
	"set_mode",
	"set_output_formatter",
	"set_path_mode",
	"stop_watching",
	"toggle_decorator_log_only",
	"toggle_global_log_file",
	"toggle_logs",
	"toggle_message_metadata",
	"w",
	"watch",
]
