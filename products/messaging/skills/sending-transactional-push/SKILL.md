---
name: sending-transactional-push
description: >-
  Set up PostHog transactional push notifications: one-off pushes that code sends to one person, such as order
  updates, sign-in alerts, new messages and reminders a person's action triggers. Use whenever the user wants to send
  a push notification from their backend, moves one from another provider (OneSignal, Firebase Cloud Messaging
  directly, Expo, Customer.io, Braze), or debugs one. Covers the push channel, the template, making it sendable from
  code, the API key, sending with the API, idempotency keys, and checking that a send arrived.
---

# Sending transactional push notifications

A transactional push is a one-off notification that a person's action triggers, such as an order update.
In PostHog, the user writes the notification as a push template, makes it sendable from code, and their backend sends it to one person with one API call.
The notification goes to every device that person registered for the template's apps.
Push setup is at https://posthog.com/docs/workflows/push-notifications.md.

## Check that the project can use it

Look for the `workflows-create-push-template`, `workflows-make-push-template-transactional-prepare` and `workflows-send-push-prepare` tools before you promise anything.

- If they are missing, transactional push is not on for the project yet, or the MCP connection lacks the scopes. Tell the user which one applies if you can tell, otherwise say both.
- Don't work around a missing tool with other tools.

## Set it up

1. Find the project's push channels: integrations of kind `firebase` (Android, and iOS through Firebase) and `apns` (iOS directly). If there are none, point the user to the push setup docs, because the app must register devices with the PostHog mobile SDK first.
2. Create the template with `workflows-create-push-template`: `type` is `push`, and `content.push` has a `title`, a `body` and the `channels` to send through. Use `{{ variables.name }}` for each value a send passes. Add `link` for where a tap goes and `data` for string values the app's code reads. The template can't read person properties.
3. Make it sendable with the `workflows-make-push-template-transactional` pair. The user must confirm, and it can't be undone. Transactional sends skip marketing opt-outs and frequency caps, so never do this for marketing.
4. The user creates a project secret API key with the Transactional push notifications scope set to Write. Never ask them to paste the key into the chat.
5. Their backend sends with `POST /api/projects/{project_id}/messaging/send/push/` and a JSON body of `template_id`, `distinct_id` and `message_data`. Show them the call in their language. Add an `Idempotency-Key` header, such as `order-shipped-<order id>`, so a retry within 24 hours doesn't send twice.

## Check a send

- A 202 means queued. The `message_id` in the response finds the run in the template's Sends tab.
- A person with no registered device for the template's apps gets nothing. The send still returns 202 and shows as skipped in Metrics. Check that the app registers the device under the same distinct ID the backend sends to.
- A device that uninstalled the app is removed after the first failed delivery.
- `transactional_push_paused` means the template's workflow was turned off. Ask the user before you turn it back on.

## Don't decide alone

- Making a template sendable, and every test or real send, need the user's confirmation.
- Don't send to a distinct ID the user did not name.
