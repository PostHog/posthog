# Workflows

Workflows is the product where a team builds workflows, broadcasts and transactional emails, and sends messages to people through them.
It also holds the channels, recipients and deliverability setup behind those messages.
This glossary sets the words for Email & Messaging, the product home for everything that sends messages.
A term marked "(Email & Messaging)" becomes true when that home ships.
Until then the UI still says Library, Message categories, and a "Messaging" setup tab.

## Language

### Navigation

**Email & Messaging** (Email & Messaging):
The product home for broadcasts, transactional emails, messaging workflows, templates and their setup, with its own sidebar.
It opens on the Overview.
_Avoid_: Messaging (as the product name), Messaging home

**Overview** (Email & Messaging):
The first page of Email & Messaging: how messages performed, what needs attention, and what sends next.
An account with nothing set up sees the next set-up step there instead.

**Calendar** (Email & Messaging):
One view of everything scheduled to send, across broadcasts and workflows, instead of one calendar per scene.

**View** (Email & Messaging):
A saved filter, sort and column set over the things you send.
A **default view** is built in, one per kind of thing you send: Broadcasts, Transactional emails and Messaging workflows.
The sidebar lists them under "Views".
_Avoid_: Folder, Tab, Segment

**Setup** (Email & Messaging):
The sidebar group for Channels, Recipients, Deliverability and Settings.
_Avoid_: Messaging (as that heading)

**Settings** (Email & Messaging):
The settings for engagement events, email tracking consent and UTM defaults.
They are the last row of Setup.

**Workflows row**:
The Products row of the Workflows product, which lists every workflow with the All / Messaging / Automations / Loops filter.
It is the home of automations and loops.
Inside Email & Messaging, the Messaging workflows view shows only messaging workflows.

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
A workflow that is not a loop and has an email, SMS or push step.
A Slack step does not make a workflow a messaging workflow.
The view is called "Messaging workflows".
_Avoid_: Drip campaign, Campaign

**Automation**:
A workflow that is not a loop and has no email, SMS or push step.
It is a view, not a noun of its own.

**Loop**:
A workflow that the Loops product created.
It shows only on the Workflows row, never inside Email & Messaging.

**Broadcast**:
A one-time or scheduled message to a group of people, on any channel.
Broadcasts send only email today.
_Avoid_: Campaign, Blast, Newsletter

**Audience**:
The group of people that one broadcast goes to.
The word never names the consent area.

**Transactional email**:
An email template that your code sends with one API call.
The view is called "Transactional emails".
_Avoid_: API send, transactional message (until a second channel ships)

**Message**:
One email, SMS or push notification that reaches one recipient, or one Slack post.
A broadcast to 1,000 people is 1,000 messages.

**Templates**:
Reusable message content.
Today every template is an email template.
API-enabled templates show a "Transactional" tag in Templates and also appear in the Transactional emails view.
**Workflow templates** are starting points for a workflow.
They live in the "New workflow" chooser, not in Templates (Email & Messaging).
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

**Recipients** (Email & Messaging):
The area that decides who may receive your messages.
It holds opt-outs and the suppression list.
_Avoid_: Audience, Subscriptions, Contacts, Consent

**Topic**:
A kind of message, either marketing or transactional.
A person can opt out of a marketing topic.
Each email, SMS or push step saves its own **transactional mark**.
The editors set the mark from the chosen topic's kind, and every transactional email has it.
An API call can set the mark directly, whatever the topic.
The mark stays as saved, even if the topic changes kind later.
A message with the mark ignores opt-outs and the frequency cap.
_Avoid_: Message category, Category, Subscription type

**Opt-out**:
A person's choice to stop one topic or all marketing messages, made on the **preferences page**.
_Avoid_: Unsubscribe list (as a noun for the area)

**Suppression list**:
The email addresses PostHog stops sending to, from bounces, complaints or manual adds.
An email with the transactional mark still reaches a suppressed address unless that address hard-bounced.
A **suppressed address** is one entry.
_Avoid_: Blocklist

**Deliverability** (Email & Messaging):
The area for whether mail arrives and how much PostHog may send.
It holds Reputation and the sending limits, which are the daily limit and the frequency cap.
