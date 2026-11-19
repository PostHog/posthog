# Wizard Cloud Run Reliability

These are internal targets. They are not a customer SLA.

Measure each SLI over one calendar month.

| SLI                         | Definition                                                                      | Initial SLO  |
| --------------------------- | ------------------------------------------------------------------------------- | ------------ |
| Dispatch success            | Accepted cloud runs that start a Temporal workflow.                             | 99.0%        |
| Worker provisioning success | Dispatched runs that provision a Wizard Worker.                                 | 99.0%        |
| Platform failure rate       | Runs that fail because of PostHog, Temporal, a sandbox, or artifact publishing. | At most 2.0% |
| Artifact handoff success    | Successful Wizard executions that create the expected artifact.                 | 99.0%        |
| Worker cleanup success      | Worker cleanup attempts that destroy the Wizard Worker.                         | 99.5%        |
| Deadline breach rate        | Cloud runs detected after their deadline.                                       | At most 0.1% |

Do not count user input failures as platform failures. Examples include an inaccessible repository and an invalid repository configuration.

## Failure codes

The Wizard writes a final `phw-error:` record to standard error when a program fails. The worker stores its `PHW_*` code on the Wizard run.

The backend stores only the code. The UI owns the user message and recovery steps. If the record is absent or invalid, use the platform error for the failed stage.

The execution activity also logs a `wizard_execution_failed` warning with the run ID, Wizard version, exit code, and the record's code and message.
The worker redacts credential-shaped values in the message, such as PostHog and GitHub tokens, URL credentials, and `Authorization` values. It then cuts the message to 500 characters.
It does not enter Temporal workflow history, run metadata, or analytics events.
To investigate a failed cloud run, search the worker logs for its run ID.
The CLI's own events, including its `$exception`, carry the same ID as `task_run_id`.

Collect latency data before you set latency SLOs. Review these targets after 30 to 60 days of production data.
