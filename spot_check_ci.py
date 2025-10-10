#!/usr/bin/env python3
import subprocess
import json
from datetime import datetime

# Get a recent frontend workflow run
run_ids = [
    ('18398304770', 'Frontend CI', '2025-10-10'),
    ('18397890426', 'Backend CI', '2025-10-10'),
]

print("SPOT CHECK: Recent Individual CI Job Timings vs GitHub Averages")
print("=" * 150)
print()

for run_id, workflow_name, date in run_ids:
    result = subprocess.run(
        ['gh', 'api', f'repos/PostHog/posthog/actions/runs/{run_id}/jobs'],
        capture_output=True, text=True
    )

    jobs_data = json.loads(result.stdout)

    print(f"{workflow_name} - Run ID: {run_id} ({date})")
    print("-" * 150)
    print(f"{'Job Name':<75} {'Actual Duration':>15} {'Labels/Runner':<35}")
    print("-" * 150)

    for job in jobs_data['jobs']:
        if job.get('started_at') and job.get('completed_at'):
            start = datetime.fromisoformat(job['started_at'].replace('Z', '+00:00'))
            end = datetime.fromisoformat(job['completed_at'].replace('Z', '+00:00'))
            duration_ms = int((end - start).total_seconds() * 1000)

            job_name = job['name'][:72] + '...' if len(job['name']) > 75 else job['name']
            runner_name = job.get('runner_name') or 'unknown'
            runner = runner_name[:32] + '...' if len(runner_name) > 35 else runner_name
            labels = ', '.join(job.get('labels', []))[:32] if job.get('labels') else 'N/A'

            print(f"{job_name:<75} {duration_ms:>13,d}ms {labels:<35}")

    print()
    print()
