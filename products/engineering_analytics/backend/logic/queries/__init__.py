"""HogQL queries for engineering_analytics.

The only module allowed to name warehouse tables (`github_pull_requests`,
`github_workflow_runs`). Logic and facade work with canonical types only.
This boundary is the future provider-Protocol seam — see SPEC.md section 7.
"""
