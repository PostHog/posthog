# Maps the `command_run_kind` stored on a run's state to the Temporal workflow that runs it.
# A generic "command" run carries its command in state; named leaves hardcode their own.
COMMAND_RUN_WORKFLOWS: dict[str, str] = {
    "command": "process-command-run",
    "append_readme": "append-readme-command-run",
}

DEFAULT_COMMAND_RUN_KIND = "command"

# The single canned command behind AppendToReadmeCommandCloudRunWorkflow. Runs from the
# repository root (the activity cd's into the checkout first).
APPEND_README_COMMAND = "printf '\\n_Touched by a PostHog cloud run._\\n' >> README.md"
APPEND_README_PR_TITLE = "Append PostHog marker to README"
APPEND_README_PR_BODY = "Automated cloud run: appended a marker line to the end of the README."
