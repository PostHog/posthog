# How people find out about self-driving PRs

Three paths bring a human to a self-driving PR. This document says what each one sends, what it records, and how an arrival in the app is tied back to the notification that produced it.

## The three paths

**GitHub.** The agent opens the PR, and the repository's own conventions decide who hears about it: CODEOWNERS, watch settings, or a person tagging a colleague. PostHog does not request reviewers itself. The PR description footer carries a link back to the inbox report (`auto_start.py`), tagged `utm_source=github`.

**Slack.** Two different products post two different cards.

| Sender                                         | Card                                             | Link                                         |
| ---------------------------------------------- | ------------------------------------------------ | -------------------------------------------- |
| `slack_inbox_notifications.py`                 | Report ready, and reviewer-added pings           | "Review in PostHog" only, never a PR link    |
| `scout_harness/slack_delivery.py`              | A scout's report, to the configured channel      | "View report in PostHog"                     |
| `tasks/.../post_slack_update.py` + `slack_app` | "Pull request opened", in the originating thread | "View PR" (github.com) and "Open in PostHog" |

The inbox card fires when a report becomes ready and actionable, which is before any PR exists, so it never carries one.

**In-app.** The person opens the inbox and finds the report themselves.

## Send events

Every successful send records one event, so non-response is measurable. Without them only arrivals are visible, and silence is indistinguishable from never having been told.

### `signals_notification_sent`

Emitted by `_deliver_route_notification` (report ready and reviewer added) and by the scout Slack delivery.

| Property                | Type        | Description                                                                   |
| ----------------------- | ----------- | ----------------------------------------------------------------------------- |
| `notification_id`       | `str`       | Also the `nid` on the link in the message, which is how an arrival joins back |
| `report_id`             | `str`       | The report the message is about                                               |
| `channel`               | `str`       | `slack`                                                                       |
| `destination`           | `str`       | `team` for a shared channel, `user` for a reviewer's own channel              |
| `recipient_attribution` | `str`       | `person` when the destination has exactly one recipient, else `group`         |
| `mentioned_user_count`  | `int`       | How many reviewers the message @-mentions                                     |
| `dispatch_reason`       | `str`       | `report_ready`, `reviewer_added`, or `scout_report`                           |
| `priority`              | `str`       | Report priority at send time                                                  |
| `source_products`       | `list[str]` | Which products the report's signals came from                                 |
| `repository`            | `str`       | Repository the report selected, when it has one                               |
| `skill_name`            | `str`       | Scout deliveries only                                                         |

A team channel is a broadcast with no single recipient, so it attributes to the team and carries its reach in `mentioned_user_count`. A personal channel attributes to that person.

Only a successful `chat_postMessage` records an event. Counting a failed send would produce a notification that reads as ignored.

`pr_notification_sent` covers the Slack-app PR card and is documented in [tasks instrumentation](../../tasks/docs/INSTRUMENTATION.md#pr_notification_sent).

## Link tagging

Every notification link is built through `tag_notification_url` (`posthog/notification_links.py`).

| Parameter      | Value                                                                                     |
| -------------- | ----------------------------------------------------------------------------------------- |
| `utm_source`   | `slack` or `github`                                                                       |
| `utm_medium`   | `notification`                                                                            |
| `utm_campaign` | `self-driving-report`                                                                     |
| `utm_content`  | `inbox_card_team`, `inbox_card_user`, `scout_delivery`, `pr_footer`, `pr_card`            |
| `nid`          | The send's `notification_id`. Omitted on the PR footer link, which belongs to no one send |

Campaign parameters rather than private names, because posthog-js already captures `utm_*` from the URL: the channel reaches analytics with no client-side change, and it survives a dropped send event.

**`utm_medium=notification` is the exclusion key.** These are internal product links, not acquisition. Any marketing or web-analytics report that breaks traffic down by source should exclude it.

## Arrivals

`inboxSceneLogic` reads the parameters when a report URL is opened, hands them to `setInboxArrival`, and every report-level inbox event then carries `notification_id`, `notification_channel`, and `notification_surface` for the rest of the session. That is what makes act-rate by channel measurable, not just open-rate.

`nid` is stripped from the URL after it is read, so a refresh cannot count as a second click on the same send. The `utm_*` parameters stay, because posthog-js reads them off the live URL.

`open_method` on `Inbox report opened` is older and answers a different question: `deeplink` means the person landed straight on a report without visiting the list, whatever brought them there.

## Known gaps

- The "View PR" button on the Slack PR card leaves posthog.com, so its clicks are invisible. Measuring them needs a redirect shim.
- A GitHub notification we did not send (a watcher, a CODEOWNERS rule firing before the PR reached us) has no send event. `pr_review_requested` records the tag itself, which is the closest available substitute.
- Reviewer assignment inside PostHog still emits no event, so the set of people a report intended to reach is only reconstructable from its `suggested_reviewers` artefact.
