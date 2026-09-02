"""Django signals other products connect to. Tasks never imports the receivers."""

from django.dispatch import Signal

# Sent once per finished agent turn with ``task_run``, ``text`` (all the turn's prose),
# ``last_text`` (the prose after its last tool call: the answer) and ``turn_key`` (stable
# per turn, so a replayed relay can be ignored).
task_run_turn_finished = Signal()
