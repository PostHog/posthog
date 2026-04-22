-- Default SQL for `python manage.py run_autoresearch_smoke`.
-- This is a contrived query whose only cost is a hard-coded sleep.
-- A working autoresearch campaign should notice the sleep call, drop it,
-- and show a ~500ms -> <10ms win in the first iteration.

SELECT sleep(0.5), 1
