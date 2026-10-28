# Onboarding a project to messaging

Use this when a project needs messaging setup before its first email, SMS or push workflow.
The goal is the same result as the in-app setup wizard, with as few messages as possible: say what is missing once, recommend a default for each choice, and ask for one confirmation.

## 1. Check the setup, and start the suggestions

Call `workflows-setup-status`.
It returns every setup step with `done`, a `next_step` and an `app_url`, plus `ready_to_send_email` and `email_sending_paused`.

The email steps only matter for workflows that send email.
An SMS or push workflow sends through its own channel, so do not ask for the email channel or domain when the workflow has no email step.

Check `email_sending_paused` first, even when every step is done.
When it is true and the workflow sends email, tell the user that email sending is paused for the project and that they need to contact PostHog support. The workflow can still be drafted, but its emails will not send.

If every step is done and sending is not paused, skip to the lifecycle in [SKILL.md](../SKILL.md).

Call `workflows-data-suggestions-list` now.
It starts a background run, so the suggestions are ready by the time setup is done.

## 2. Say what is missing, in one message

List only the open steps, in order, with a short line each.
Group them by who does them:

- **Steps the user does in the app.** The email channel and the sending domain need a domain the user controls and DNS records at their DNS provider. Share each step's `app_url`. Do not try to do these steps over MCP.
- **Steps you can do now.** The sending rules. Recommend the defaults below and ask the user to confirm.
- **Optional steps.** Opt-out categories and an email template. Mention them, and share the `app_url`, but do not block on them.

### Sending rules to recommend

Read the current values with `workflows-sending-rules-get` first.

- **Frequency cap.** When there is no cap, recommend at most 1 marketing message every 2 days (`marketing_frequency_cap_max_messages: 1`, `marketing_frequency_cap_window_days: 2`). Offer a different cap or no cap if the user wants one. Transactional messages are never capped.
- **Engagement events.** Recommend turning `capture_workflows_engagement_events` on, so sends, opens, clicks and bounces show up as events. Say that these events count toward the project's event usage.
- **Tracking consent.** Leave `email_tracking_consent_mode` as it is unless the user asks. If they mention GDPR or consent, explain `opt_out` and `opt_in`.

A cap the project already has stays as it is. Do not replace it with the recommendation.

## 3. Apply what the user confirmed

Call `workflows-sending-rules-update` with only the fields the user agreed to.
It needs a project admin. If it returns a permission error, tell the user that a project admin has to set the sending rules, and move on.

## 4. Offer a first workflow

Read the suggestions with `workflows-data-suggestions-get` (or the result from step 1).
Show up to three, each with its name, trigger event and one line on why it fits.
Offer to start from scratch as well.

When the user picks a suggestion, build it with `workflows-data-suggestions-create`.
It saves a draft. Hand over to the lifecycle in [SKILL.md](../SKILL.md): test it, then enable it only after the user says so.

When there are no suggestions, ask what the workflow should do and build it from the lifecycle.

## When the user skips the app steps

A draft can exist before the domain is verified.
If the workflow has an email step and `ready_to_send_email` is false, say clearly that its emails will not send yet, and share the `app_url` again.
When `email_sending_paused` is true, the domain is fine but sending is paused for the project, so tell the user to contact PostHog support instead.
Call `workflows-setup-status` again when the user says they finished a step.
