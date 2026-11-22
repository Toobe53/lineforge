# LineForge — shared error type.
# GPL-2.0-or-later.


class LineForgeError(RuntimeError):
    """An error the user is expected to fix (missing binary, empty scene, bad settings).

    The UI catches these and shows `str(exc)` instead of a traceback.
    """
