"""Slack `action_id`s for the interactive buttons signals puts on its report messages.

On the facade because they are the contract with the Slack app: signals renders the buttons
(`slack_report_actions.py`), the Slack app's interactivity webhook routes the clicks on these ids and
calls back through `facade.api`. Its own module, and free of imports, so routing a click costs the
Slack app nothing at import time.

Each id is wire format. A message already sitting in a channel carries the id it was posted with
forever, so renaming one breaks every button already delivered.
"""

SLACK_CREATE_PR_ACTION_ID = "signals_create_pr"
