"""The one error type the command reports to the user (no stack trace)."""


class TtsError(Exception):
    """A failure the user can act on: missing setting, bad input, or an error from Azure."""
