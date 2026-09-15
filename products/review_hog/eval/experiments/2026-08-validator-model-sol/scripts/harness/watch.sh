#!/bin/bash
# Emits one line whenever the 75215 report's artefact counts or status change; exits when the run ends.
R=$1; SP=${REVIEWHOG_EXP_SCRATCH:?set REVIEWHOG_EXP_SCRATCH to a scratch dir for the run markers}
prev=""; quiet=0
while true; do
  cur=$(PGPASSWORD=posthog psql -h localhost -p 5432 -d posthog -U posthog -Atc "
    SELECT r.status || ' | ' || coalesce(string_agg(a.type || '=' || a.n, ' ' ORDER BY a.type), '-')
    FROM review_hog_reviewreport r
    LEFT JOIN (SELECT report_id, type, count(*) n FROM review_hog_reviewreportartefact GROUP BY report_id, type) a ON a.report_id = r.id
    WHERE r.pr_number = 75215 GROUP BY r.id, r.status" 2>/dev/null)
  if [ "$cur" != "$prev" ]; then echo "$(date +%H:%M:%S) $cur"; prev="$cur"; quiet=0; else quiet=$((quiet+1)); fi
  [ $((quiet % 20)) -eq 19 ] && echo "$(date +%H:%M:%S) quiet ${quiet}m: $cur"
  if [ -f $SP/$R.end ]; then echo "$(date +%H:%M:%S) RUN ENDED: $(tail -1 $SP/$R.log) | $cur"; exit 0; fi
  if ! pgrep -f "^python manage.py start_temporal_worker" >/dev/null; then echo "$(date +%H:%M:%S) WORKER DOWN"; fi
  sleep 60
done
