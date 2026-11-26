# Deleting events

Deleting events cannot be undone, so support needs the exact scope before they run anything.
A ticket with everything below lets support start the request the day they read it.
A ticket without it gets a reply asking for each missing item.

When the person would rather keep the events and remove only some properties, tell them before you write anything.
Support usually cannot do that, so ask whether they want the events deleted instead, and write the ticket only if they do.

There are two routes ([docs](https://posthog.com/docs/privacy/data-storage#deleting-specific-events)):

- **Support runs the deletion.** The ticket needs everything below, including the query and its count.
- **Support turns on self-serve event deletion** for the person's organization, so they file their own requests, in the PostHog app (project settings, "Deletion requests") or through the data deletion requests API. Both stay off until support turns them on. Organization admins and owners can use it, and so can members who are given access. A project can have up to 5 requests in progress, and PostHog reviews each one before any events are deleted. No MCP tool files these requests, so you can't file one for them.

| They want to delete                          | Self-serve event deletion                                                                                                                                                       |
| -------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Whole events that one query can select, once | Yes, in the app or the API, after support turns it on                                                                                                                           |
| Events that arrive later, or on a schedule   | No. PostHog selects the matching events once, when it processes the request. To delete by age, point them to [events retention](https://posthog.com/docs/data/events-retention) |
| A property, but keep the events              | No                                                                                                                                                                              |
| Persons or recordings                        | No, and they don't need it: both are self-serve already, so use the routes in `answering-privacy-questions`                                                                     |

Use the first route for any other one-off event deletion, and when you aren't sure. Neither route deletes events on a schedule. If one query can't select the events, give a query and a count for each part.

When the second route fits, always tell the person they can ask for it, in the app and the API, and what it can and can't delete. Say in **Request** which route they want.
A ticket asking to turn it on needs the region, the project, the reason, who is asking, and what they want to delete. Add the query and count when they have them, and say that they ask for event deletion to be turned on, and not for support to run the deletion.
Never say that event deletion is turned on, or that it will be.

## What the ticket must include

**Region and project ID.**
Take both from the project lookup in the skill: the project link carries the ID, and the Region line gives the region.
IDs repeat across regions, so always give both.
A query covers one project, so give a query and a count for each project.

**One query that selects exactly the events to delete.**
Write it in HogQL against `events`:

- Pin both time bounds to UTC, such as `timestamp >= toDateTime('2026-10-01 00:00:00', 'UTC')`. A bound without a timezone is read in the project's timezone, so copying it unconverted deletes a different set of events.
- End with a fixed time in the past, using `<`. Never use `now()`, because the deletion runs days later.
- When the person gives no start, start at the day of the project's first event, and say so. When a bound they give is approximate, ask them for the exact time. Do not pick one for them.
- When they ask for every event of some persons or IDs, the dates they mention describe the data, not the scope. Start at the project's first event, end at a fixed time before today, and say so. If they gave their own count, say whether the query's count matches it.
- Name the events with `event = '...'` or `event IN (...)`. If every event in the window should go, leave out the event condition and say so.
- Filter on the property that identifies the scope, such as `properties.$host` for one web app.
- Keep to conditions on `events`. `JOIN`, `LIMIT` and `HAVING` do not map onto the deletion request.
- `!=`, `NOT` and `NOT IN` also match events where the property is missing. Check that the person wants that.

**The count that query returned.**
Ask the person to run it in the SQL editor as `SELECT count() FROM events WHERE <the same conditions>` and give you the count.
Support checks the deletion against this number and stops if they differ.

**The person's confirmation.**
Show the person the query and the count before you write the ticket, and ask them to confirm that this is exactly what to delete.
Ask why they need it deleted, and put their reason in **Request** without adding to it. A privacy or security reason decides the ticket's `topic`.
Then **Request** asks to delete that many events, such as "Please delete the 3,817 events the query below returns".
A ticket that gives the query and its count and asks for the deletion counts as their confirmation, so support does not ask again.

**Who is asking.**
Their name and role in the organization. Ask for both. Never infer them from what your connection can access.

When you hand it over, tell the person to send it from their own PostHog account, through the draft tool or the support widget, and not from another email address.
Support checks that the requester is a member of the organization that owns the project.
A ticket sent through the draft tool arrives unverified, so support may wait for the person to reply from the support panel in PostHog before deleting anything.

## Leave out

- How the data got there, beyond one sentence in **Request**. Support needs the scope, not the history.
- Asking support to keep the persons. Deleting events leaves persons in place.
- Volume estimates for other event types, and properties outside the scope.
- Anything about other projects, unless each one has its own query and count.

## Example

````text
Staging test events to delete from our live project

---

Request:

Our staging build sent test checkout events to our live project in the first week of October 2026. Please delete the 3,817 events the query below returns. We'd like support to run this deletion, rather than turning on self-serve event deletion for us.

---

Details:
- Project: [Web app](https://us.posthog.com/project/12345)
- Region: US Cloud
- Requested by: Jane Doe, engineering lead
- Events: `checkout_started` and `checkout_completed` from the host `staging.example.com`
- Query, which returned 3,817 events:

```sql
SELECT count()
FROM events
WHERE timestamp >= toDateTime('2026-10-01 00:00:00', 'UTC')
  AND timestamp < toDateTime('2026-10-08 00:00:00', 'UTC')
  AND event IN ('checkout_started', 'checkout_completed')
  AND properties.$host = 'staging.example.com'
```

---

Already checked:
- Claude Code checked: the persons in these events have 41,200 real events that must stay, so deleting the persons doesn't fit
- I tried: the query returns 3,817 events, all from `staging.example.com`
````
