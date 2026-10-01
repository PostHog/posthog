# Workflows

Workflows and Broadcasts send messages to the people in a PostHog project.
This glossary covers the words for who those messages can reach.
The UI uses the bold terms; the code keeps its own names, listed with each term.

## Audience

**Audience**:
The area of Workflows that lists the email addresses a project can send to, with their topic preferences, suppression and engagement.
_Avoid_: Contacts, subscribers, audience (for who one broadcast targets, see batch audience)

**Recipient**:
One email address PostHog may send to, and the unit of the Audience list.
Topic statuses and suppression attach to the recipient, not to a person: zero, one or many persons can hold the address as their `email` property.
Code: `MessageRecipientPreference.identifier`.
_Avoid_: Contact, subscriber, user

**Topic**:
A kind of message, defined by the customer, that a recipient can subscribe to or unsubscribe from.
**All marketing** is the reserved topic that covers every marketing message.
Code: `MessageCategory`; all marketing is the `$all` key.
_Avoid_: Category, list, subscription group

**Topic status**:
A recipient's choice for one topic: **subscribed**, **unsubscribed** or **no preference**.
No preference means marketing messages are sent, because marketing is opt-out by default.
Code: `OPTED_IN`, `OPTED_OUT`, `NO_PREFERENCE`.
_Avoid_: Opt-in, opt-out (as nouns for the status)

**Suppressed**:
A recipient that is never sent to, for any message type, because of a bounce, a spam complaint or a manual entry.
Suppression is independent of topic status.
Code: `MessageSuppression`.
_Avoid_: Blocked, blacklisted, unsubscribed

**Unreachable person**:
A person with no `email` property.
Audience shows unreachable persons as a coverage gap, never as a recipient.
_Avoid_: Missing recipient, anonymous recipient

**Engagement events**:
The `$workflows_email_*` events captured when an email is sent, delivered, opened or clicked, bounces, is marked as spam, or when a recipient unsubscribes.
A project captures them only when the `capture_workflows_engagement_events` setting is on.
_Avoid_: Email metrics (that is `app_metrics`), tracking events

## Batch audience

**Batch audience**:
The persons one broadcast or batch workflow targets, resolved from its filters when it runs.
It is not the Audience area.
Code: `services/batch_audience.py`, `services/audience_v2.py`, the `workflows-audience-query-v2` flag.
_Avoid_: Audience (alone), segment
