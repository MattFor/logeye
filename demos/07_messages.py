"""
log("...") as a better print(): {} placeholders, $variables from the scope,
the current file's path, and output without the timestamp when you want it.

    python demos/07_messages.py
"""

from logeye import log, toggle_message_metadata

user = "Ada"
attempts = 3

log("Hello {}, {} attempts left", user, attempts)
log("Hello {name}!", name=user)

# $variables come from wherever log() is called
log("Hello $user, $attempts attempts left")

# $fpath, $rpath and $apath: this file's name, relative path and absolute path
log("This message comes from $fpath")

# Assigned, a message is logged under its name and returned as the string
greeting = log("Welcome back, $user")

# Values are inserted as text and never expanded a second time
pattern = "$user"
log("A literal pattern: $pattern")

toggle_message_metadata(False)
log("No timestamp or location on this line")
toggle_message_metadata(True)
