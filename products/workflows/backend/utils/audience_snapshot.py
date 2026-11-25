from datetime import timedelta

# A run waits this long for its audience to resolve, then fails. The query itself is capped well below it.
AUDIENCE_SNAPSHOT_WAIT_LIMIT = timedelta(hours=2)
