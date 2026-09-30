#!/bin/bash
# usage: run.sh <label>   — starts one DB-only review of PR 75215, records start/end epochs.
R=$1; SP=${REVIEWHOG_EXP_SCRATCH:?set REVIEWHOG_EXP_SCRATCH to a scratch dir for the run markers}
cd "$(cd "$(dirname "$0")" && git rev-parse --show-toplevel)" || exit 1
date +%s > $SP/$R.start
flox activate -- bash -c "DJANGO_SETTINGS_MODULE=posthog.settings python manage.py run_review --pr-url https://github.com/PostHog/posthog/pull/75215 --team-id 1 --user-id 1" > $SP/$R.log 2>&1
echo "exit=$?" >> $SP/$R.log
date +%s > $SP/$R.end
