"""Replay Vision Temporal workflows and activities.

The worker registry (`WORKFLOWS`, `ACTIVITIES`) lives in `registry.py`, not here, so importing a
leaf module such as `temporal.constants` does not eagerly pull in the whole activity graph. That
eager import used to create a cycle: business modules (`quota`, `prompt_evaluation`) import
`temporal.constants`, and pulling in every activity dragged `create_observation` back into the
half-initialized `quota` module.
"""
