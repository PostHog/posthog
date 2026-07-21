"""Shared helpers for the PostHog support CLI scripts (scrub/prune).

Import the names you need straight from the defining module - `lib.errors`, `lib.console`,
`lib.posthog_api` - rather than re-exporting them here. Scripts run directly
(`python products/support/scripts/<name>.py`), which puts this directory on sys.path, so
`lib.<module>` imports without any packaging.
"""
