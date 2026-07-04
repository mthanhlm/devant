"""devantlib — the devant CLI split into lazy-importable modules.

Kept deliberately empty: hooks import only devantlib.common + devantlib.guard on
the Write/Edit hot path, so nothing heavy may load from the package root.
"""
