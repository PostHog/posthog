"""Shared exception type for the support CLI scripts."""


class PostHogScriptError(Exception):
    """An expected, operator-facing failure (bad auth, an API error, an aborted run).

    Scripts catch this at the top level and print it as a one-line error, so raising it
    (rather than letting an arbitrary exception escape) is how a script fails cleanly.
    """
