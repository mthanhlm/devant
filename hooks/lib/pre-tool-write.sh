#!/usr/bin/env bash
# PreToolUse (Write|Edit|MultiEdit): the edit guard. Delegates the whole parse+evaluate+emit
# to guard_write.py in ONE python process (no shell field-splitting), which denies block-constraint
# violations / direct .devant edits / secrets, asks on warn rules, records the touched file, and
# prints the PreToolUse decision. Degrades to allow (exit 0) when devant/python are unavailable.
LIB="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$LIB/common.sh"

dv_enabled || exit 0
dv_has_devant || exit 0
python3 "$LIB/guard_write.py"
exit 0
