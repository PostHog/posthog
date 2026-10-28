# The closing question

End the report with one question about what happens next. Don't write a sentence of offers instead.
Each option is a step you can do now. Mark the one you'd pick as recommended.
Use your client's question tool if it has one. Otherwise, number the options.
If the user said they are away, list the options in the report instead of asking.

## Options

Offer an option only when its condition holds.

- **Launch the experiment.** Drafts only. Picking it is the user asking for a launch. Follow the launch steps in `managing-experiment-lifecycle`, including the pre-launch checklist.
- **Set a reminder to check the results on <date>.** Launched experiments only. A draft has no start date to count from, so `managing-experiment-lifecycle` offers the reminder once the experiment launches. See [Set the reminder](#set-the-reminder).
- **End <name>.** Only when you found a running A/A test or other experiment that should end, and the user hasn't said to keep it. Call `experiment-end`. It freezes that experiment's results and leaves its feature flag as it is.
- **Ask users what they think, with a short survey linked to the experiment's flag.** Only for a user-facing change that passes Gate 1 in [qualitative-feedback.md](../../diagnosing-experiment-health/references/qualitative-feedback.md), and only once: at launch, leave it out if you offered it at creation. See [Create the survey](#create-the-survey).

## Set the reminder

Call `reminder-create` with these fields. Load `managing-reminders` for the others.

- `title`: "Check the results of <experiment name>"
- `team`: the project's numeric id
- `resource_type`: `experiment`
- `resource_id`: the experiment's numeric id, sent as a string (`"123"`)
- `scheduled_at`: the experiment's `start_date` plus `running_time_calculation.recommended_running_time` days, rounded up. Read both with `experiment-get`. Use the user's date instead when they give one, and ask for a date when no running time is stored. Leave `recurrence_interval` and `cron_expression` out, so it fires once.

Then tell the user the date, and that the reminder is an in-app notification only they see.
`reminder-create` returns no link, so link the experiment with its `_posthogUrl`.

## Create the survey

Follow [qualitative-feedback.md](../../diagnosing-experiment-health/references/qualitative-feedback.md) for its shape, and load `creating-surveys` for the rest.
Attach it the way the app does. Pass the experiment's `feature_flag.id`, from `experiment-get`, as `linked_flag_id`, whatever the rollout, and leave out `linkedFlagVariant` so it reaches everyone in the experiment.
Then link the survey with its `_posthogUrl`, and tell the user its responses show on the experiment's User feedback tab, which lists only surveys linked to its flag.
