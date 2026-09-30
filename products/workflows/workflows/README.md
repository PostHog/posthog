# PostHog's own workflows

This folder holds workflows that PostHog runs in its own project, kept as YAML files.
A CI job checks them on every pull request that changes this folder, and applies them when the change lands on `master`.

Each `.yaml` file is one workflow. The job reads no other extension.
To read another, add its glob on its own line in the job's `files` input.
The `key` in the file is the workflow's identity in the project, so it never changes, and the file name matches it.
The fields are described by the JSON Schema PostHog serves at `GET /api/projects/:id/hog_flows/code_schema/`.
The [writing-workflows-as-code](../skills/writing-workflows-as-code/SKILL.md) skill explains how to write, check and apply a file.

## Check a file by hand

Use a personal API key with the `hog_flow:read` scope, and set `POSTHOG_API_KEY` to it. `code_check` writes nothing.
A project secret key (`phs_`) works once [#104202](https://github.com/PostHog/posthog/pull/104202) is deployed.

```bash
jq -Rs '{content: .}' products/workflows/workflows/welcome-new-signups.yaml |
  curl --fail-with-body -H "Authorization: Bearer $POSTHOG_API_KEY" -H 'Content-Type: application/json' \
    --data-binary @- "https://us.posthog.com/api/projects/2/hog_flows/code_check/" | jq
```

The response is a plan: whether applying the file creates or updates the workflow, and which steps it adds, changes or removes, with the people in each removed step.
A file with mistakes gets HTTP 400 and a list of up to 50 errors, each with a line, a column, a `why` and a `fix`.

## What the CI job does

`.github/workflows/workflows-as-code.yml` runs only when a change touches this folder or the job's own file.
It uses the [posthog-workflows-action](https://github.com/Silthus/posthog-workflows-action), pinned to the commit of v0.1.2, which sends each file with curl and jq.

- On a pull request, it checks every file. Errors show as annotations on the file, and the plan goes to the job summary.
- On a push to `master`, it applies every file. A file creates its workflow, updates it, or changes nothing when it already matches.
- When its key is not set, each job prints one line and succeeds, as a warning in the apply job. Pull requests from forks get no secrets, so they pass this way.
- A request that gets no answer, HTTP 408, 409 or a 5xx is sent once more after two seconds.
- When the folder holds no `.yaml` file, each job prints one line and succeeds, so deleting the last workflow file does not fail it.

Applying a file replaces the workflow's content in PostHog, including any edit made in the workflow editor, so change the file instead.
The file also sets the status: `status: draft` keeps a workflow off, and a person turns it on by changing the file to `status: active`.
To retire a workflow, delete its file, then archive the workflow in PostHog once that change is merged. Deleting the file alone deletes nothing. Check and apply refuse a file whose workflow is archived, so an archived workflow whose file remains fails every pull request that touches this folder and every apply on `master`.

## Settings

A repository admin sets these in the repository settings. Create the environment, limited to `master`, before the pull request that adds this job merges: the merge runs the apply job, and GitHub creates a missing environment without that limit.

| Name                           | Kind                                                 | Holds                                                                          |
| ------------------------------ | ---------------------------------------------------- | ------------------------------------------------------------------------------ |
| `POSTHOG_WORKFLOWS_API_KEY`    | Repository secret                                    | An API key with `hog_flow:read`, for the check on pull requests                |
| `posthog-workflows`            | Environment, deployment branches limited to `master` | Holds the write key, so a pull request run cannot read it                      |
| `POSTHOG_WORKFLOWS_API_KEY`    | Secret on the `posthog-workflows` environment        | An API key with `hog_flow:write`, for the apply on `master`                    |
| `POSTHOG_WORKFLOWS_PROJECT_ID` | Repository variable, optional                        | The project id. Defaults to `2`                                                |
| `POSTHOG_WORKFLOWS_HOST`       | Repository variable, optional                        | The PostHog host. Defaults to `https://us.posthog.com`. It must use `https://` |

Both secrets have the same name and hold different keys. The apply job names the environment, so it reads the environment's write key. The check job reads the repository's read key.
If the environment has no `POSTHOG_WORKFLOWS_API_KEY`, the apply job reads the read key and every apply fails with HTTP 403.

## Before the keys are set

- The job calls the `code_check` and `code_apply` endpoints, so set its keys only after those endpoints serve in production ([#108920](https://github.com/PostHog/posthog/pull/108920)). Until then the job passes without doing anything.
- A personal API key with `hog_flow:read` (check) or `hog_flow:write` (apply) works today. A project secret key (`phs_`) works once [#104202](https://github.com/PostHog/posthog/pull/104202) is deployed. Until then PostHog answers 401 to it.
- Marking an applied workflow as managed by code, and recording the file and commit it came from, waits for [#103540](https://github.com/PostHog/posthog/pull/103540), and then for the job to send them. Until then an applied workflow stays editable in PostHog, and the next apply replaces any edit.
- The welcome workflow sends no email yet. It marks each person who signed up a day ago and has an email address with `welcome_email_ready`. An email step needs the id of one of the project's email senders, and check and apply refuse any other id, so a placeholder would fail both jobs. To send the email, replace that step with an `email` step whose `from.integration_ids` holds the sender's id from PostHog, under Workflows, Channels. The pull request's check shows whether the id is right.
