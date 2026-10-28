# Workflows

Workflows is where a team builds automated workflows and sends messages to people: broadcasts, transactional emails, and the channels, recipients and deliverability behind them.
This glossary fixes the words for the Messaging home in the new sidebar.
A term marked "(Messaging home)" becomes true when that home ships behind `today-rail-nav`.
Until then the UI still says Library, Message categories, and a "Messaging" setup tab.

## Language

### Navigation

**Messaging** (Messaging home):
The one home in the sidebar for broadcasts, transactional emails, messaging workflows, templates, channels, recipients and deliverability.
Inside the home the word labels nothing else.

**Workflows row** (Messaging home):
The sidebar row that lists every workflow, with the All / Messaging / Automations / Loops filter.
It is the home of automations and loops.
Messaging > Workflows shows the messaging view only.

**Setup** (Messaging home):
The group heading for Channels, Recipients and Deliverability, when a layout needs one.
_Avoid_: Messaging (as that heading)

**Settings** (Messaging home):
The messaging settings: engagement events, email tracking consent and UTM defaults, behind a settings control on the home.

**Calendar** (Messaging home):
One view of everything scheduled to send, across broadcasts and workflows, instead of one calendar per scene.

### What you send

**Workflow**:
The one noun for an automated sequence of steps that a trigger starts.
Messaging workflow and automation are views derived from its steps, and loop from the product that created it.
None of them is a separate object type.
_Avoid_: Journey, Campaign, Flow

**Messaging workflow**:
A workflow with an email, SMS or push step.

**Automation**:
A workflow with no email, SMS or push step.
It is a view, not a noun of its own.

**Loop**:
A workflow that the Loops product created.
It shows only on the Workflows row, never inside Messaging.

**Broadcast**:
A one-time or scheduled message to a group of people, on any channel (email today).
_Avoid_: Campaign, Blast, Newsletter

**Audience**:
The group of people that one broadcast goes to.
It never means the consent area.

**Transactional email**:
An email template that your code sends with one API call.
The section label is "Transactional".
_Avoid_: API send, transactional message (until a second channel ships)

**Message**:
One email, SMS, push or Slack post delivered to one recipient.
A broadcast to 1,000 people is 1,000 messages.

**Templates**:
Reusable message content, today email templates.
API-enabled templates show a "Transactional" tag in Templates and also appear under Transactional.
**Workflow templates** are starting points for a workflow.
They live in the "New workflow" chooser, not in Templates (Messaging home).
_Avoid_: Library

Broadcasts, transactional emails and workflows have no umbrella noun.
_Avoid_: Sends, Campaigns

### Setup

**Channel**:
A medium PostHog can send through: Email, SMS, Push or Slack.
Slack stays a channel even though a Slack-only workflow is an automation.
_Avoid_: Connection, Sender, Integration (as the section name)

**Sending domain**:
The setup of the email channel: a verified domain to send from.

**Recipients** (Messaging home):
Who may receive your messages.
It holds opt-outs and the suppression list.
_Avoid_: Audience, Subscriptions, Contacts, Consent

**Topic**:
A kind of message that a person can opt out of.
_Avoid_: Message category, Category, Subscription type

**Opt-out**:
A person's choice to stop one topic or all messages, made on the **preferences page**.
_Avoid_: Unsubscribe list (as a noun for the area)

**Suppression list**:
The email addresses PostHog never sends to, from bounces, complaints or manual adds.
A **suppressed address** is one entry.
_Avoid_: Blocklist

**Deliverability** (Messaging home):
Whether mail arrives and how much may be sent: Reputation plus the sending limits (daily limit and frequency cap).
