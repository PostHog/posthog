# Topics

A topic looks after one thing a person is responsible for. Its inbox contains reports submitted by agents, tasks and their conversations hold work and questions, and the topic keeps what it learns as facts. Context references are passive; monitoring requires an explicit watch or routine. This document is the contract between the crates that implement topics. Each crate is headless and testable without a network; the desktop host renders them.

The [architecture paper](meep/architecture/index.html) explains how routines, agents and the inbox fit together. This reference is the contract for the crates.

## Crates

| Crate | Owns | Depends on |
| --- | --- | --- |
| `meep-store` | SQLite records, transactions and the full-text search index. | none |
| `meep-ai` | Authenticated System One decisions and chat completions through the PostHog AI gateway. | none |
| `meep-topic` | The domain model and every state transition. Pure: no I/O, no clock, no randomness (callers pass `now` and IDs). | none |
| `meep-policy` | Decides whether an action runs, waits for the person or is refused, and selects structurally eligible skip rules. Builds rules from answers. | `meep-topic` |
| `meep-ingest` | Turns connector events into messages, removes duplicates, preserves explicit thread keys and routes events to watching topics. | `meep-topic` |
| `meep-connections` | The connected services, their health, which topics may use each one, and secrets. | `meep-store` |
| `meep-connectors` | PostHog and MCP polling, webhook mapping and delivery checkpoints. | `meep-connections`, `meep-ingest`, `meep-posthog`, `meep-store`, `meep-topic` |
| `meep-wire` | Shared request, response and change-stream types. | `meep-topic` |
| `meep-client` | SQLite replica, optimistic commands, outbox and server synchronization. | `meep-topic`, `meep-store`, `meep-wire` |
| `meep-engine` | One worker per topic. Applies events, runs routines on triggers, starts agent runs, delivers messages between topics, aggregates what needs the person and publishes changes. | `meep-ai`, the domain and storage crates, `meep-workflows`, `meep-posthog` (feature) |
| `meep-posthog` | PostHog API, OAuth, Tasks (agent runs), chat log decoding, MCP and flow dispatch, with optional features for OAuth, Tasks, chat, MCP and workflows. | none |

## Model (`meep-topic`)

IDs are `Uuid` newtypes with `Display`, `FromStr`, `Serialize` as a string: `CommandId`, `TopicId`, `ThreadId`, `MessageId`, `TaskId`, `FactId`, `RuleId`, `GoalId`, `WatchId`. Timestamps are `chrono::DateTime<Utc>`.

- `Topic { id, name, mission, goals: Vec<Goal>, rules: Vec<Rule>, facts: Vec<Fact>, routines: Vec<RoutineInfo>, created_at }`. Passive PostHog references are stored separately from watches. A routine may own watches through `RoutineBinding { id, name, trigger, backend, external_id, watches: Vec<Watch> }`. Existing legacy watches and workflows are retained; creating a topic does not provision or activate a sorter.
- `Watch { id, connection: String, kind: String, key: String, label: String }`. `kind` is service-defined: `channel`, `insight`, `flag`, `label`, `topic`. A watch with `connection = "topic"` and `key = <TopicId>` receives that topic's messages.
- `Source`: `User`, `Topic(TopicId)`, or `Connection { connection, channel }`.
- `Message { id, producer: Producer, origin: Option<Origin>, author, at, text, external_id: Option<String> }`. `Producer` is `Routine(id)`, `PostHogTask(task)`, `User` or `System`. `Origin { connection, channel, external_id, thread_hint, author, at }` identifies the sending topic for a published report. Agent report threads carry `report_sources` with described evidence and source references; older source threads may also retain their original connector record. `Message::reply_target()` derives the reply destination from the origin. Stored messages with the old `source` field still load.
- `Thread { id, subject, summary, state, review_version, question_source, pending_questions, parent_task, messages, outcomes, key, unseen, created_at, updated_at }`. `key` groups messages about the same thing.
- `ThreadState`: `Sorting`, `NeedsYou { reason, suggestions: Vec<Suggestion> }`, `Handled`, `Skipped { reason, rule: Option<RuleId> }`.
- `Suggestion`: `DraftReply { draft, task_title }`, `MakeTask { title }`, `Investigate`, `AnswerInChat`, `AcceptEvidence { message, task, fact }`, `ResolveFacts { changed, other, resolution }`, `Leave`.
- `Outcome`: `Task(TaskId)`, `Fact(FactId)`, `File(String)`, `Reply { to: Source, text }`, `Note(String)`.
- `Task { id, title, column, added_by: Actor, from_thread, assignment: Option<InboxAssignment>, parent: Option<TaskId>, review_before_start, review_version, approval_rule, worker: Option<String>, action: Option<Action>, result, draft, log: Vec<LogEntry>, created_at, updated_at }`
- `Column`: `Todo`, `InProgress`, `NeedsYou`, `Done`.
- `Actor`: `User`, `Agent`, `Routine(String)`, `Topic(TopicId)`, `Inbox(ThreadId)`.
- `Action { kind: ActionKind, label, done_label, payload: serde_json::Value, depends_on_facts: Option<Vec<FactId>> }`. `ActionKind(String)` names a class of side effect, such as `copy-change`, `slack-reply`, `merge-pr`. The approval question reads "Do {kind description} without asking from now on?", so each kind has a human description.
- `Fact { id, text, provenance: Provenance { author, via, at, thread: Option<ThreadId> }, superseded_by: Option<FactId>, invalidated_by: Option<FactId>, withdrawn_at: Option<DateTime<Utc>> }`
- `Rule { id, text, effect, from_task: Option<TaskId>, created_at }`; `RuleEffect`: `Allow(ActionKind)`, `Ask(ActionKind)`, `Deny(ActionKind)`, `Skip(Matcher)`. `Matcher { connection, channel }` holds optional exact source filters. The rule text states what to skip.
- `Goal { id, text, progress: Option<Progress> }`; `Progress::Target { current, target, unit }` or `Progress::Guardrail { current, low, high, unit }`.
- `Activity { at, actor, text, subject: Ref }` where `Ref` is `Thread`, `Task`, `Fact`, `Rule`, `Routine(String)` or `Topic`.

`TopicState` aggregates a `Topic`, its threads, tasks and activity. Every operation takes `now` (and new IDs where needed), validates, mutates and returns `Vec<Change>`. Invalid transitions return a typed error and leave the state untouched.

- Internal and legacy threads: `receive(message, key)` appends to the newest thread with the same key unless that thread was skipped by a rule; otherwise opens a `Sorting` thread. A message appended to a resolved thread marks it `unseen`. `sort(thread, Decision)` where `Decision` is `Handle { summary, outcomes }`, `Ask { summary, reason, suggestions }` or `Skip { reason, rule }`. `answer(thread, suggestion)` resolves a `NeedsYou` thread: a draft creates a `NeedsYou` task with the draft; a task suggestion creates a `Todo` task. Choosing `Investigate` assigns an investigation task to the original message. Accepting evidence saves the proposed fact or attaches the source to its target task, and leaving dismisses the question. The next waiting question then becomes visible. `mark_seen(thread)`.
- Tasks: `add_task`, `start(task, worker)`, `progress(task, worker)`, `submit(task, action, result, draft)` moves to `NeedsYou`, `approve(task, edited_draft)` releases a held start or logs approval of the displayed action and moves it to `Done`, `send_back(task, note)` returns it to `InProgress` with the note in the log, `move_task(task, column)` for user drags, and `complete(task, result)` for work that needed no approval. Sending a proposal back or moving its task withdraws the executable action. An agent can call `ask_user` with a question to pause its own task in Needs You. The person replies in the task conversation to continue the investigation. The question and reply stay on the task and leave the inbox unchanged. Terminal execution failures and interrupted starts appear in Needs You with the diagnostic. Moving the task to To do permits a new attempt.
- Memory: `add_fact`, `supersede_fact(old, new)`, `remove_fact`.
- Context: `set_mission`, `add_goal`, `update_goal_progress`, `add_rule`, `remove_rule`, and passive reference commands `AddContextSource`, `RemoveContextSource` and `SetContextSources`. `set_watch` configures monitoring separately.
- `Change { seq, at, kind: ChangeKind }` names what changed (`ThreadOpened`, `ThreadUpdated`, `TaskAdded`, `TaskMoved`, `FactAdded`, `RuleAdded`, `TopicUpdated`, and so on) with the IDs involved, so a UI or the change feed can update without diffing.
- `needs_you(&self)` lists the threads in `NeedsYou` and the tasks in `NeedsYou`. `digest(since)` counts messages, tasks, facts and skips.

Everything serializes with serde. JSON must round-trip.

## Policy (`meep-policy`)

- `decide(rules, action) -> Verdict`: `Run`, `Ask` or `Refuse`, with the rule that decided it. With no matching rule the verdict is `Ask`. Later rules override earlier ones.
- `skip_candidates(rules, message)` returns eligible skip rules in reverse precedence order. System One evaluates each rule as written.
- `rule_from_approval(task, always: bool)` builds `Allow(kind)` with readable text such as "Always do copy-only changes without asking."
- `Limits { max_hops, max_runs_per_hour }` and `hop_ok(hops)`: inter-topic messages carry a hop count; delivery stops past the limit.

## Intake (`meep-ingest` and `meep-engine`)

- `Event { connection, kind, external_id, channel, thread_hint: Option<String>, author, at, text, attributes: serde_json::Value }`.
- `Deduper` keyed by `(connection, external_id)` over a `SeenStore` trait with an in-memory implementation.
- `group_key(event) -> Option<&str>` exposes an explicit Slack thread, PR number or other provider key. The engine scopes it to the account and channel. A message without a hint opens a provisional conversation. System One chooses among up to 32 recent open conversations and a new thread. Candidates include handled source conversations and threads with pending questions. A confident continuation publishes `ThreadJoined { incoming, target }`.
- `route(event, bindings: &[(TopicId, RoutineBinding)]) -> Vec<(TopicId, String)>` matches connection, kind and key, and names the routine that owns the matching watch.
- `Connector` trait: `name()`, `poll(since) -> Vec<Event>`; `FixtureConnector` is available in tests and under the `fixtures` feature.

## Sources and routines

A topic can store passive PostHog context references. Adding a reference does not watch the object, provision a workflow or start monitoring. A person may explicitly request a source watch or routine; configured source workflows receive matching observations. Existing stored workflows and watches remain in place, but new topics do not provision Sort inbox.

A running agent task may publish a report to its own topic or another topic shared with its PostHog account. The report has a title, findings and described evidence with source identifiers or links. The inbox lists agent-published reports only. A report also carries a priority (P0–P4), an impact sentence, a proposal, and evidence with a kind and time. The person chooses **Implement** or **Investigate**, which sends the topic's agent a queued chat message (`Chat` with `queue: true`) carrying the report's ID, summary, proposal and evidence, asks about it in chat, or resolves or dismisses it with a reason (`SetReportVerdict`); viewing a report does not create work. Questions are asked and answered in the task conversation. Fact conflicts are reviewed in Facts, file revision conflicts in Files, and both also appear in Needs you.

For a configured source routine, Meep stores observations and dispatches the workflow. A workflow can record notes or facts, publish workflow agent findings, drop an observation with a reason, or attach evidence to existing work where supported. Authenticated Report callbacks file workflow findings in the bound inbox. Existing observations remain available for investigation. Each routine retains pending observations and the newest 500 finished observations, visible in `list_routines` and the Routines page.

Supported routine templates are `scout` (each morning an agent looks for problems and publishes one report per finding), `daily-brief`, `weekly-goals`, and `digest-then-drop`. A template agent step can carry a short `title` with its `text` as the agent brief. Templates are available through `GET /v1/routine-templates` and `POST /v1/topics/{id}/routines {template, sources?}` or `create_routine`. New `system1_sort` classifier steps and the retired `sort-inbox` and `urgent-only` templates are rejected. Previously stored workflows are not silently replaced.


### Setup and PostHog Scout reports

A new topic opens one setup run (`"setup": true` in the brief). The agent reads the mission, adds the PostHog objects it is about as context, proposes measurable goals, records baseline facts, creates the `scout` routine and turns on the Scout feed, then reports what it did in the topic chat.

`TopicSettings.scout_feed` (`SetScoutFeed`, the `set_scout_feed` tool, or the Context switch) brings PostHog Scout reports into the inbox: `None` is off, an empty string takes every ready report in the project, and a search term takes matching ones. The server polls `signals/reports` every two minutes with the topic's PostHog grant (`inbox:read`), imports each new report once (keyed by `ReportSources.external`), and maps its priority, lead, affected-users metric, Solution section and signals to a Meep report. Resolve or Dismiss on an imported report is written back to PostHog's report state (`inbox:write`) once.

### Engine events and built-in stages

A PostHog routine can also start on an engine event: `message_arrived`, `task_added`, `task_moved`, `fact_changed` or `routine_failed`, with an optional exact-match filter on the event's fields (`create_routine` trigger `{"type":"event","on":"task_moved","filter":{...}}`). Meep starts the workflow itself with the event as variables, using the same dispatch key and observation record as a source.

Use `SetTopicSetting { key, enabled }` to control these topic settings.

| Setting | On | Off |
| --- | --- | --- |
| `check_facts` | Each fact change is compared with current facts. | Nothing is disputed automatically. |

A running task can publish a report with the `publish_report` topic MCP tool. Pass `title`, `summary` and `evidence` entries with `description` and `source_id`; legacy `body` and `sources` are also accepted. An optional `topic` addresses a topic shared with the current account. A scheduled brief can use `list_source_observations` to read recent evidence for its own topic. Board tasks belong to the agent. `AddTask` offers work immediately. Use `AddConfiguredTask` with `start: false` to queue it in To do. `StartTask { task }` or moving the card to In progress releases it with its saved run preferences.

Meep starts PostHog workflows through a manual trigger built on `template-source-webhook` with `event: "$workflow_triggered"` and `distinct_id: "{request.body.user_id}"`, and declares every variable it sends. Branching on Meep's values is not offered: PostHog branch conditions read event properties, and the run API delivers Meep's values as workflow variables.

## Legacy intake and sorting

The thread and sorting machinery below supports existing data and explicitly configured flows. It does not mean that source messages or decisions appear in the report-only inbox, or that a new topic automatically starts a sorter.

Ingest commits each message and its pending sorting job together. New threads start in `Sorting`. Replies keep their earlier outcomes while the worker evaluates the new evidence. The topic worker processes arrivals in order and resumes pending work after restart. It releases the topic edit lock during inference and checks the conversation and policy before publishing the result. Provider replay uses the original connection and external ID throughout.

`ModelSorter` calls System One for incoming observations assigned to sorting. It supplies the topic mission, current facts, goals, conversation, open task choices and eligible automations. The model can keep or skip an observation, save a sourced fact, attach evidence to an open task, create assigned work, or ask a question. Written skip rules take precedence. Low confidence surfaces in Needs You. A failed model call leaves the message unsorted and retries after 1, 2, 4, 8 and 16 minutes; the thread carries `sort_retry {failures, next_at, reason}` meanwhile. After the sixth failure it asks the person, with a **Sort again** choice that requeues the original message. Legacy source threads can retain summaries and queued questions. They are not agent reports in the inbox. Proposed evidence that needs clarification waits for an explicit choice.

An inbox task can belong to a person, a bound PostHog workflow, or the investigation agent backed by PostHog Tasks. A step needing permission starts in Needs You. Approving its start releases it to the assigned executor. Later proposed actions still go through action policy. A task the person creates in the app is just its brief: it carries a stand-in title and `untitled: true` until it starts, when the worker takes the title PostHog generated from the brief (sent as `naming_source`). A remote workflow receives the task ID, title and source thread with a durable dispatch key. The worker records results on the task. A person can turn an entry in `Findings.follow_ups` into a queued, linked task with **Create task**. Delivery receipts and failures stay on the originating work. A late receipt preserves newer work on the same card. Task-originated workflow approvals use that card. Inbox items show a report, its sources and linked tasks. Topic chat has its own surface. Manual and older tasks without an inbox assignment retain host routing.

The topic’s `start-follow-up` action rule governs existing agent-proposed work and investigation leads assigned to an agent or routine. An Allow rule admits eligible work. Ask and the default hold the start in Needs You. Deny blocks approval. Choosing “Always allow” on an approved start adds a standing rule. A System One permission requirement always holds the task.

A chat envelope creates a `Sorting` thread on the replica and server and goes to the topic agent (see [One agent per topic](#one-agent-per-topic)); chat messages are not classified. Source discovery for onboarding uses System One scores to rank the topic’s granted sources against its mission. The replica caches that order per topic.

## One agent per topic

A topic has one agent and one continuous conversation with it: a single PostHog Task with the `ChatAnswer` assignment, the *session*. Setup is its first turn. The session is the topic's newest `ChatAnswer` task (`session::session_task`); there is never a second one. Each turn is a new run that resumes the last (`resume_from_run_id`), so the agent keeps its memory and gets fresh topic MCP tools. When a turn finishes, Meep stops its idle interactive run, since PostHog caps open sandboxes and the next turn resumes from it anyway. A failed turn is retried on the same task.

**The topic inbox.** Everything for the agent lands in the topic inbox (`meep-engine/src/session.rs`) and nothing calls the agent directly:

- the person's chat messages (`Command::Chat`, optionally `queue: true`);
- notes from Meep: an approval the person gave or declined, facts changed outside the conversation (grouped into one note);
- the agent's own `later` to-dos, offered once each.

**Turns.** When the session is idle, the worker starts one turn with everything waiting: the person's messages first, then an "Also waiting" list. The agent decides what to do with it. The reply goes to the person's newest message; a turn nobody asked for (a to-do coming up, an approval note) gets a short "Meep" line in the chat to answer under.

**You come first.** A message from the person reaches a working agent straight away: Meep checks the run once more (an answer it already finished is posted, not lost), then stops it and resumes the conversation with the message and the full turn it interrupted, so the agent answers and then finishes that work (steering; a message delivered into a live PostHog run would get its tool calls refused). `queue: true` (⌘↵ in the app) waits for the current work instead. Stop (`CancelRun` on the session) ends the current work and puts the to-dos it was on back in the list.

**Permission prompts.** When the agent asks for something its rules hold for review (activating or running a routine), the request waits on the session task in Needs you and the tool result tells the agent to say what it asked for and end its turn; the run keeps its tools until then. Approving runs the action and the agent hears about it in its next turn; declining (`SendBack`) does the same with the note. Writing in the chat while a prompt is open declines it. In the conversation, `ask_user` returns "ask in your reply" instead of pausing.

**Side work.** The agent adds tasks with `plan_task` only for work that should not happen now:

| `for` | Assignment | Who does it |
| --- | --- | --- |
| `you` | `Human` | The person. Never runs. |
| `later` | `Session` | The same agent, offered in its next idle turn under "Also waiting"; it finishes with `complete_task`. |
| `sub_agent` | `Investigate` | A separate PostHog Tasks run, only for work that can run in parallel or that a simpler, faster model can do. When it finishes or fails, its result goes to the topic inbox as a note for the agent's next turn. |

Each entry in `TopicState.routine_report_runs` groups one routine and trigger event, with its latest delivery time, provider agent run IDs and published thread IDs. The folded chat line can use the thread count, including zero.

## Fact reconciliation

Every committed addition, removal, supersession or invalidation queues a direct System One comparison on that topic. The worker keeps the withdrawn assertion and its provenance so it can identify dependent claims after a removal. It checks the other current facts that existed at the edit, including their source messages and the source of any replacement. It retries unavailable model calls after a restart and discards stale results if the evidence changes during inference.

With hosted decisions, a fact edit that other current facts may depend on adds a note to the topic inbox, merged with other changes into one note for the agent's next turn; the agent's own edits are not checked, and no task is created. A supported correction links the superseded assertion to the winning fact ID. A withdrawal can retire a dependent assertion with an `invalidated_by` link. Withdrawing a replacement preserves its ID and withdrawal time so earlier corrections stay traceable. Current memory, search, chat and new investigations omit retired assertions. When evidence is ambiguous, Needs You shows both assertions and their sources. Disputed fact IDs accompany current claims in new task context. External actions declare their dependencies in `Action.depends_on_facts`. An empty list is independent. An omitted list waits for all open disputes. The server checks evidence at approval and delivery. Resolving the dispute releases permitted work whose evidence survived. A retired dependency requires revision. The person can choose which assertion to keep, keep both, or decide whether a remaining assertion has independent support.

## Lifecycle, undo and usage

- `RenameTopic {name}`, `ArchiveTopic`, `UnarchiveTopic`, `DeleteTopic`. An archived topic stops intake, routines and agent starts, pauses topic-owned PostHog schedules, and leaves Needs You and default search. A deleted topic is removed with its files and views after the tombstone revision reaches devices.
- `DeleteTask {task}`, `ArchiveThread {thread}`, `DeleteFile {path}` (revision history kept until the topic is deleted).
- `RestoreFact {fact}` brings back a forgotten fact; `RestoreRule {rule}` brings back a removed rule within 30 days.
- `TopicState.usage` replicates agent starts in the rolling hour against the cap, and System 1 calls and workflow dispatches per day.
- `DELETE /v1/connections/{id}/credentials` revokes an account's tokens on the server and stops its polling; the app calls it on sign-out.
- `PUT /v1/settings/public-base-url` sets the HTTPS public address at runtime; it is stored in the server's data directory. `MEEP_PUBLIC_BASE_URL` still works.
- Agent runs time out after 60 minutes without progress, and a run is cancelled in PostHog when its card leaves In progress or on `CancelRun {task}`. The server stamps time itself; a device's `issued_at` is kept for display. The change feed keeps the latest revision per topic after 7 days; receipts and seen keys expire after 30 days.

## Connections (`meep-connections`)

- `Connection { id, kind, label, account, health, grants: Vec<TopicId> }`; `Health`: `Ok { checked_at }`, `Expired { since, detail }`, `Failing { since, detail }`.
- `Registry` persisted in `meep-store`: `add`, `remove`, `set_health`, `grant`, `revoke`, `can_use(topic, connection)`.
- `SecretStore` trait with `MemorySecrets` and `KeychainSecrets` (macOS `security` command).

## Engine (`meep-engine`)

- `Engine::new(store, policy limits, agent: Arc<dyn Agent>, sorter: Arc<dyn Sorter>)`.
- Commands: `ingest(event)`, `create_topic`, user actions (`answer`, `approve`, `send_back`, `move_task`, `add_task`, `chat`, `set_mission`, `add_rule`, `remove_rule`, `set_watch`, `reconnect`), and `send_to_topic(from, to, text, hops)`.
- Queries: `topic(id)`, `topics()`, `needs_you()` across topics, `subscribe()` for changes.
- `Sorter` supplies thread selection, disposition, written routine conditions and chat intent. The server injects `ModelSorter` using the PostHog account granted to the topic.
- `Agent` trait: `start(run: AgentRun) -> RunHandle` and `poll(handle) -> RunState`. `AgentRun` carries the topic mission, current facts, rules, the task and its source thread. `FixtureAgent` finishes runs with scripted results; `PostHogAgent` uses Tasks.
- Routines are PostHog workflows. Stored local routines from older versions load as failing bindings with a message to recreate them in PostHog.
- Approval: when an agent or routine submits an action, the engine calls `policy::decide`. `Run` approves the action and queues delivery. `Ask` puts it in `NeedsYou`. `Refuse` records the rule and stops dispatch.

## Where things run

Topics keep working when the Mac is closed, and the Mac app works without a network. Both hold because the server is the source of truth for automation and the app keeps a full local replica.

| Piece | Runs | Role |
| --- | --- | --- |
| `meep-server` | Topic server host | Runs `meep-engine`, connectors, agents and routine callbacks. Exposes the command API, the sync API, files, webhooks and a live change stream. Storage sits behind traits so the host can change. |
| `meep-client` | In the Mac app | A local replica of every topic in SQLite, an outbox of commands, optimistic apply, background sync and a change feed for the UI. The app reads and writes only the replica. |
| Routine backend | PostHog Workflows, plus built-in stages on the topic server | A bound PostHog workflow runs remotely and calls the topic server to apply its operations. Built-in stages run in the engine. |

### Owners and privacy

Every topic, view, connection, file and setting belongs to one owner, and nothing is shared between owners. The server runs a separate engine, store, worker set, credential store and view service per owner. A device token belongs to exactly one owner, and the device middleware selects that owner from the token alone. On every device route, the live stream, search and both MCP servers, an object of another owner answers exactly like one that does not exist. Mentions, `list_topics`, cross-topic reads and topic-to-topic messages resolve inside one owner. Webhooks, polling and workflow callbacks are routed by the owner of the connection; older unqualified URLs keep mapping to the original owner.

`meep-server owner add|list` and `meep-server device add --owner <id>` manage owners and device tokens. The health response returns `owner_id`, and `Client::pair` keys the Mac's replica, outbox and stored sign-in by server and owner, so pairing with another owner never reuses a cache or replays an outbox. Existing single-user data becomes the implicit owner's on first start, offline and in place.

### Commands

A person sends a `meep_topic::Envelope { id: CommandId, topic: TopicId, issued_at, command }`. Its `Command` is tagged by `kind` and carries the IDs needed by the operation, including `AddTask { id, title }`, `Approve { task, expected_review, edited_draft, always, rule_id }`, `Answer { thread, expected_review, suggestion, task_id }`, `Chat { message_id, text, task_id }` and `Reply { thread, text }`. A chat thread uses the message UUID. `Envelope::create()` builds the state for `CreateTopic { name, mission }`. On an existing topic, `TopicState::apply(&Envelope)` is pure. The server accepts the same envelope through `Engine::apply`, which returns `Applied { revision, changes }`. `snapshot(topic)` returns `TopicSnapshot { revision, state }`. `changes_since(cursor)` returns ordered `TopicRevision { topic, revision }` entries and the next exclusive cursor. Start with zero.

- Answers, approvals and revision requests are bound to the displayed review version. The server rejects stale decisions. `AllowReviewedAction` also verifies the action kind and the rule ID reserved by that specific approval. A current Deny rule blocks approval and the resulting standing permission. Queued deliveries check for Deny again before dispatch.
- Chat can create a bound PostHog workflow draft. The engine applies the topic’s `routine-activate` policy to activation requests from chat and the desktop. Allow queues activation, Ask creates a review, and Deny leaves the draft inactive. Routine approvals identify the installed binding version. Rebinding withdraws pending proposals. Retry routine returns an assigned task to its automation as a new run. Failed or unconfirmed delivery is recorded on the original task and moves it to Needs You when the attempt is still current. Confirmed approved executions retain their own handles until completion, including after a card move or server restart.
- The client applies a command to its replica at once, stores it in the outbox and shows the result. Nothing waits for the network.
- The server applies commands in arrival order, remembers applied command IDs so a retry is harmless, and returns the topic revision.
- When the client receives a newer server state for a topic, it replaces its base copy and re-applies the commands still in its outbox. A command the server rejected is dropped and reported to the UI with the reason. Refused file edits remain recoverable on the originating replica until the person saves or discards the copy. The replica uploads each edit with its base revision and stable operation ID. Divergent edits become immutable alternatives at the same path. A shared Needs You thread records the human choice. Selecting the alternative publishes a fresh head. Both original revisions remain available.
- Work done by the server (sorting, agent results, routine callbacks, messages from other topics) reaches the client as new topic revisions on the change stream.

### Pluggable seams

- `Store` (records and command log) and `Blobs` (files): SQLite and a directory now; Postgres and object storage later.
- `RoutineBackend`: `bind`, `start`, `status`, `health`. `PostHogRoutines` uses `meep-posthog` flows. A routine changes a topic only through `Engine::routine_callback(topic, routine, secret, RoutineOp)`, where `RoutineOp` includes `AddTask`, `AddFact`, `Ask`, `Send`, `Note` and `RefreshView`; the callback is authenticated with a per-routine secret.
- `Agent` and `Sorter`, as above.
- `Transport` in the client: HTTP now, anything that can carry commands, state and a change stream later.

### Sources

Every source flows through the person's PostHog account, so there is one sign-in and one place to grant or revoke access.

- PostHog's own data (insights, feature flags, event counts) comes from the PostHog MCP server, called with the person's PostHog OAuth token.
- Other services (Slack, GitHub, Linear and so on) come from the MCP servers connected in the PostHog account, through PostHog's MCP gateway. A tool's approval state in PostHog decides whether a topic may call it.
- Webhooks cover anything that can push to `/v1/ingest/{connection}`.

PostHog Workflows owns every trigger. Slack, GitHub and other services feed PostHog, a workflow decides what matters, and its webhook step pushes into the topic through the server's one signed endpoint, `/v1/ingest/{connection}`. The server accepts webhooks only from PostHog workflows. A watch with no workflow behind it falls back to polling an MCP tool, keeps a cursor, and reports health when a tool fails or loses its grant. There are no direct clients for third-party services.

## Workspace views

A view is a named JavaScript page with an emoji tile and one or more authoring conversations. It has its own UUID. Each device places it in a sidebar section alongside its topics. The desktop mounts a published generation with `meep_render::mount`. Opening a conversation or its history keeps the script mounted. Script interaction state lasts for the mount. Source checkpoints and conversations survive closing the app.

### Storage and commands

`meep_wire::views::ViewEnvelope { id, view, at, command }` carries one device command. The replica commits it to its SQLite outbox and immediately projects the edit for the UI. The regular sync cycle pushes pending edits in order, installs the authoritative response, and replays remaining edits over the new base. Permanent rejections appear in the same rejection feed as topic edits.

| Device endpoint | Contract |
| --- | --- |
| `GET /v1/views` | Current workspace views with source checkpoints, conversation turns and provider activity. |
| `POST /v1/views/commands` | Accept a `create`, `ask`, `settings`, `restore` or `delete` envelope and return the authoritative view. A repeated envelope returns the current snapshot. |
| `POST /v1/views/{id}/sources` | Read a source using `{source, tool, arguments}`. |
| `GET /v1/stream` | A `views` event tells the replica to refresh its view collection. Reconnecting refreshes the collection as well. |

Creation starts a conversation with the command UUID as its session ID. Asking with that session ID resumes its PostHog Task. A fresh session ID starts a separate Task. Requests for the same view run in arrival order. The server commits the command receipt, view, and authoring state through the engine store. It saves a dispatch reservation before contacting Tasks and persists the confirmed task and run IDs. After restart, queued turns dispatch and confirmed runs resume polling. An interrupted, unconfirmed launch appears in the conversation for inspection. Deletion tombstones the record and revokes access.

### Cloud authoring and reachability

Set `MEEP_PUBLIC_BASE_URL` **on the Meep server** to its externally reachable HTTPS base. For a local server, forward a public HTTPS tunnel to the local listener (the desktop default is `127.0.0.1:47950`) and restart the server with the tunnel base configured. A reverse proxy can preserve a path prefix. Keep the tunnel available throughout the run. PostHog's sandbox cannot connect to the Mac’s loopback address. Use the same publicly routed base when configuring workflow webhook callbacks at `/v1/routines/{topic}/{routine}/callback`.

The server starts an interactive PostHog Tasks run with an HTTP entry named `meep-view` in `imported_mcp_servers`. Its URL is `{MEEP_PUBLIC_BASE_URL}/v1/views/{id}/mcp`. The authorization header carries a fresh bearer capability scoped to the active turn on that view. The server stores its fingerprint and keeps it out of the desktop replica. A missing public base surfaces in the conversation. After configuring it, send another request to build the view.

`POST /v1/views/{id}/mcp` implements stateless Streamable HTTP with JSON-RPC initialization, notifications, ping, tool discovery and tool calls. Paired-device endpoints use device authentication. The MCP requires the run credential.

| MCP tool | Result |
| --- | --- |
| `read_view` | Current title, tile, generation and source. |
| `write_view` | Accept `expected` and complete JavaScript `source`, optionally `title`, `icon` and `color`. Validate loading, initialization, render trees and design rules with the native script contract. Return diagnostics and the new generation. |
| `patch_view` | Replace one unique literal (`old`, `new`) against `expected`, with the same validation and publication rules. |
| `design_system` | Read the host contract, script guide, native declarations, design guide or an example. |
| `list_sources` | Discover topic IDs, file and collection operations, native PostHog reads, and approved read-only tools on connected installations. |
| `read_source` | Inspect live data using the same source, tool and arguments as a mounted script. |

Validation errors return MCP tool errors. Publication checks the generation again after validation, so concurrent edits and restores preserve the displayed source. Restoring copies a selected checkpoint into a new generation.

### Everything from chat: the topic MCP

Everything a person can do in Meep can be done by asking in chat. The agent behind chat is a PostHog Tasks run, and Meep gives every topic run (chat answers, agent tasks and setup) an HTTP entry named `meep-topic` in `imported_mcp_servers`. Its URL is `{MEEP_PUBLIC_BASE_URL}/v1/topics/{id}/mcp`, and its bearer capability is minted for that run. The server saves only the capability's fingerprint, inside the run handle, and accepts it while the engine still observes that run on that topic. Finishing the run revokes it. **Without `MEEP_PUBLIC_BASE_URL`, runs start without the MCP** and cannot change anything; the server logs that once and the run instructions tell the agent to say so.

`POST /v1/topics/{id}/mcp` uses the same stateless Streamable HTTP contract and `Origin` check as the view MCP. Device tokens are not accepted. Changes apply only to the run's own topic. Read tools take an optional `topic` to read another topic granted to the same PostHog account, the boundary chat mentions already use. A write tool given another topic fails. Invalid input, unknown IDs and refused changes return MCP tool errors (`isError`).

Changes are topic commands (or, for agent replies, an engine transition under the same policy), so the domain model validates them and they replicate to devices as ordinary revisions. The tools act as the agent and never stand in for the person: there is no approve tool, and anything that needs approval waits in Needs You.

| Area | MCP tool | Input → result |
| --- | --- | --- |
| Topic | `get_topic` | `{topic?}` → mission, goals with progress, watches, current facts, rules, routines and counts (Needs You threads and tasks, columns, facts, disputes). |
| | `set_mission` | `{mission}` → `SetMission`, 1 to 4000 characters. |
| | `add_goal` | `{text, target?: {current, target, unit}, guardrail?: {current, low, high, unit}}` → `AddGoal`. |
| | `update_goal_progress` | `{goal, current, target?, low?, high?, unit?}` → `UpdateGoalProgress`, keeping the goal's other values. |
| | `add_rule` | `{text, effect: ask\|deny\|skip, action_kind?, connection?, channel?}` → `AddRule`. Allow rules are refused: they come from the person's approvals. |
| | `remove_rule` | `{rule}` → `RemoveRule` for Allow and Skip rules. Ask and Deny rules are the person's to remove. |
| Knowledge | `list_facts` | `{topic?, include_retired?}` → facts with provenance, dispute state and links. |
| | `add_fact` | `{text}` → `AddFact` with provenance author `Meep agent`, via `PostHog task <id>`. |
| | `supersede_fact` | `{fact, text}` → `SupersedeFact`. |
| | `remove_fact` | `{fact}` → `RemoveFact`. |
| Sources | `list_sources` | `{topic?}` → the watchable sources ranked as `GET /v1/sources?topic=` ranks them. |
| | `add_context_source`, `remove_context_source` | Add or remove a passive PostHog reference; neither starts monitoring. |
| | `watch_sources` | `{keys}` → `SetWatch`, keeping existing watches. Every key must match exactly one source. |
| | `unwatch_sources` | `{keys}` → `SetWatch` without those watches. Every key must be watched. |
| Inbox | `list_threads` | `{topic?, limit?}` → agent-published reports in the topic inbox. |
| | `get_thread` | `{topic?, thread}` → an authorized thread with messages, sources, linked tasks and any legacy review details. |
| | `publish_report` | `{topic?, title, summary, evidence: [{description, source_id}]}` → publish an agent report in the current or shared topic. Legacy `body` and `sources` are also accepted. |
| Tasks | `list_tasks`, `get_task` | `{topic?, column?}`, `{topic?, task}` → tasks with action, draft, result and (for one task) the log. |
| | `plan_task` | `{title, brief?, for}` → `PlanTask` in To do. `for` is `you` (side work the person does), `later` (the topic agent picks it up in its own conversation) or `sub_agent` (a separate PostHog Tasks run, only for completely separate long work). |
| | `move_task` | `{task, column}` → `MoveTask`. Tasks in Needs You or held for start approval stay with the person. |
| | `complete_task` | `{task}` → `MoveTask` to Done, under the same restriction. |
| | `send_back` | `{task, note}` → `SendBack` to withdraw a proposed action for revision. |
| Files | `list_files`, `read_file` | `{topic?}`, `{topic?, path, revision?}` → revisioned UTF-8 files up to 256 KiB. |
| | `write_file` | `{path, text, expected_revision}` → a new revision through `Engine::write_file`. `0` creates a file; a stale revision is refused. |
| Routines | `list_routines` | `{topic?}` → routines with binding, trigger, health and last run. PostHog routines add status, steps, schedules and the workflow link. |
| | `list_routine_templates` | → the template list above. |
| | `set_routine_sources` | `{routine, keys}` → replaces that routine's sources; each key moves from its current routine. |
| | `create_routine` | `{template, sources?}` or `{name, description?, trigger, steps, enabled?, depends_on_facts?}`. A `{"type":"source","keys":[...]}` trigger moves those sources to the new routine. Steps include `report_to_topic` ops `note`, `fact`, `agent` and, for source triggers, `drop`; direct report/question and classifier steps are rejected. The observation key is filled in automatically → creates the PostHog workflow, binds it and requests activation under the `routine-activate` policy. Returns the binding, flow ID, status and `{origin}/project/{project}/workflows/{flow}/workflow`. |
| | `set_routine_enabled` | `{routine, enabled, depends_on_facts?}` → activation under policy, or `draft` to pause. |
| | `run_routine` | `{routine}` → `StartRoutine` under the `routine-run` rule. A person's Run now is direct. |
| | `propose_action` | `{task?, kind, label, done_label, payload, draft?, depends_on_facts}` → submits the action for the run's task to the approval gate. |
| | `bind_routine` | `{flow_id}` → binds an existing PostHog workflow with `Engine::bind_routine`. Its PostHog status is unchanged. |
| Workspace | `list_topics` | → this topic and those granted to its account, with missions and Needs You counts. |
| | `create_topic` | `{name, mission}` → `CreateTopic`, then grants the caller's PostHog account so the new topic's setup conversation can start. |
| | `list_views` | → views with their latest authoring request and state. |
| | `create_view` | `{prompt}` → a view `create` command, which starts the view authoring flow above. |

The view authoring MCP (`meep-view`) is unchanged.

#### The Meep skill

`crates/meep-engine/src/skill.md` is the instruction block every Meep Tasks run receives (`meep_engine::MEEP_SKILL`, included at build). It explains topics, the inbox, tasks, facts, sources, rules, files, routines and views; when to use which tools; that changes go through tools and are never claimed without a tool result; the approval rules; and the chat reply style. PostHog Tasks takes no per-run instructions (skills come only from uploaded skill bundles or the user's skill store), so the skill leads every task description, right after the attribution marker. A topic run follows it with `## Run context` (`meep_engine::RUN_CONTEXT_HEADING`) and its JSON context, which carries the run-specific `instructions`. A view run follows it with its authoring instructions. The `meep-topic` MCP also returns the skill as its `initialize` instructions.

#### Routine triggers and steps

A trigger is `{"type":"schedule", ...}`, `{"type":"event","events":[...]}`, `{"type":"source","keys":[...]}` or `{"type":"manual"}`. A schedule takes either an RFC 5545 `rrule` body or `hour`, an optional `minute` and `days` (`MO`…`SU`, every day by default). It also takes an IANA `timezone` (UTC by default) and an optional `starts_at`. The server creates it through the workflow's `schedules/` endpoint. The steps are:

- `report_to_topic` with `{op: note|fact, text}` calls the routine callback as a `Note` or `AddFact` operation. A source trigger can also use `{op: drop, reason}`. The text is a PostHog Hog template. Each run and step sends a stable `Idempotency-Key` derived from `event.uuid`.
- `delay` takes `{duration}`, such as `30m`.
- `webhook` takes `{url, method?, headers?, body?}` for an HTTPS endpoint.

For analysis, use `report_to_topic` with `{op: agent, text}`. The older spelling `op: task` also provisions a workflow agent. Meep writes the mission, goals, context references and instructions into the workflow prompt at creation. PostHog runs Create AI task, waits for completion and forwards its reports_json output to the bound Report callback. Each finding becomes an inbox thread. An empty array records zero findings.

Creation first posts a complete draft and its schedule, so PostHog validates the workflow before anything is bound. The server then binds the flow through `Engine::bind_routine`, which replicates the routine to clients like any other binding. A final update writes the new callback secret into the report steps and sets the status. If PostHog rejects the draft, the tool returns PostHog's message. If binding fails, the server archives the draft.

#### Setup conversation

A server-hosted engine calls `Engine::enable_topic_setup`. Each topic created with `CreateTopic`, from the app or the `create_topic` tool, then commits a pending setup marker in its first revision. Once an agent can take the topic's work (a healthy PostHog account is granted to it), the worker opens the setup conversation in one revision. It adds a chat message from "Meep" and a `ChatAnswer` task titled `Set up this topic` (`meep_engine::SETUP_TITLE`), and marks the setup as started. The run takes the same path as a chat answer. It carries `"setup": true` and setup instructions in its context, and the full `meep-topic` MCP when a public base exists. It inspects the topic and sources, watches what the mission needs, sharpens the mission if it is vague, and adds one to three measurable goals. It creates routines only for clearly recurring work. Its answer, a summary of what it set up and what it needs from the person, appears as the reply in that chat thread. Without `MEEP_PUBLIC_BASE_URL` the run has no tools; its reply says it cannot change the topic because the server has no public address, and proposes the setup instead. The person steers it by chatting; each message continues the same conversation. The marker lives in the stored topic, so there is at most one setup per topic across restarts. Topics created before this feature, or while `Server::without_topic_setup` is in effect, have none.

#### Task attribution

`PostHogAgent::create_task` is the only place Meep creates PostHog Tasks. Agent tasks, chat answers, setup and view authoring all use it. Each description starts with a stable marker line, `[meep topic:<uuid>]` or `[meep view:<uuid>]`, followed by the Meep skill. PostHog's `origin_product` has no Meep value yet, so by default none is sent and PostHog applies `user_created`. Set `MEEP_TASK_ORIGIN` on the server (or call `PostHogAgent::with_task_origin`) to send one once PostHog accepts it.

### Script data and workflow refresh

Call `host.call("topics", "tasks", {topic})` from initialization or a refresh command. `tasks`, `threads` and `facts` return collections for any topic. `files` lists names. `file` returns UTF-8 text and `table` returns `{columns, rows}` for CSV, TSV and JSON. Both take an additional `path`. The desktop uses replicated topic data and cached files offline. Cloud agents read the server's authoritative records. PostHog reads use `host.call("posthog", tool, args)`, or the installation UUID as the source for connected services. The server checks the connected installation’s current approval and read-only annotation before each call.

A scheduled or event-triggered PostHog Workflow can send a `RefreshView` operation to its authenticated routine callback with `{"kind":"RefreshView","view":"<view UUID>","data":...}`. Its result is saved on the bound topic and replicated with that topic’s revision. Scripts read it with `host.call("topics", "routine_data", {topic})`, which returns the latest payload for the mounted view. Implement `commands.refresh` to update a mounted page when topic data changes. Signed callbacks and command receipts use the existing routine backend.
