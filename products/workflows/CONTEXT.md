# Workflows

Workflows is the product where a team builds automated workflows and sends messages to people through broadcasts, transactional emails and messaging workflows.
It also holds the channels, recipients and deliverability setup behind those messages.
This glossary sets the words for the Messaging home in the new sidebar.
A term marked "(Messaging home)" becomes true when that home ships behind `today-rail-nav`.
Until then the UI still says Library, Message categories, and a "Messaging" setup tab.

## Language

### Navigation

**Messaging** (Messaging home):
The one home in the sidebar for broadcasts, transactional emails, messaging workflows, templates, channels, recipients and deliverability.
Inside the home, the word names nothing else.

**Workflows row** (Messaging home):
The sidebar row that lists every workflow, with the All / Messaging / Automations / Loops filter.
It is the home of automations and loops.
Messaging > Workflows shows the messaging view only.

**Setup** (Messaging home):
The group heading for Channels, Recipients and Deliverability, when a layout needs one.
_Avoid_: Messaging (as that heading)

**Settings** (Messaging home):
The settings for engagement events, email tracking consent and UTM defaults.
They open from a settings control on the home.

**Calendar** (Messaging home):
One view of everything scheduled to send, across broadcasts and workflows, instead of one calendar per scene.

### What you send

**Workflow**:
The one noun for an automated sequence of steps that a trigger starts.
Its steps decide whether it shows as a messaging workflow or an automation.
The product that created it decides whether it is a loop.
These views are not separate object types.
A broadcast and a transactional email each have their own noun.
Neither is a workflow, even though the code runs each of them as a workflow.
_Avoid_: Journey, Campaign, Flow

**Messaging workflow**:
A workflow with an email, SMS or push step.
A Slack step does not make a workflow a messaging workflow.

**Automation**:
A workflow with no email, SMS or push step.
It is a view, not a noun of its own.

**Loop**:
A workflow that the Loops product created.
It shows only on the Workflows row, never inside Messaging.

**Broadcast**:
A one-time or scheduled message to a group of people, on any channel.
Broadcasts send only email today.
_Avoid_: Campaign, Blast, Newsletter

**Audience**:
The group of people that one broadcast goes to.
The word never names the consent area.

**Transactional email**:
An email template that your code sends with one API call.
The section label is "Transactional".
_Avoid_: API send, transactional message (until a second channel ships)

**Message**:
One email, SMS, push or Slack post that reaches one recipient.
A broadcast to 1,000 people is 1,000 messages.

**Templates**:
Reusable message content.
Today every template is an email template.
API-enabled templates show a "Transactional" tag in Templates and also appear under Transactional.
**Workflow templates** are starting points for a workflow.
They live in the "New workflow" chooser, not in Templates (Messaging home).
_Avoid_: Library

Broadcasts, transactional emails and workflows have no umbrella noun.
_Avoid_: Sends, Campaigns

### Setup

**Channel**:
A medium that PostHog can send through, which is Email, SMS, Push or Slack.
Slack stays a channel even though a Slack-only workflow is an automation.
_Avoid_: Connection, Sender, Integration (as the section name)

**Sending domain**:
The setup of the email channel.
It is a verified domain that PostHog sends email from.

**Recipients** (Messaging home):
The area that decides who may receive your messages.
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
The area for whether mail arrives and how much PostHog may send.
It holds Reputation and the sending limits, which are the daily limit and the frequency cap.
