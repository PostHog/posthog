---
name: working-with-meep
description: Use a Meep topic's mission and context to answer in chat, set up native PostHog scouts for ongoing monitoring, and explain their findings.
---

Use the assigned topic ID with `meep-topic-get` to read the mission, rules, facts, selected sources and linked scouts. Use PostHog data to answer one-time questions directly. A linked insight, flag or data source by itself is passive context.

In the main topic conversation, use `meep-task-start` to delegate independent work to board tasks when a separate sandbox can make progress without the main sandbox’s files or intermediate work. Continue independent work in the main conversation while the child runs. Give each task a clear title and a self-contained brief with the expected result. Generate a distinct request ID for each task and reuse it on retries. Use `meep-task-wait` with the selected board item IDs when the next step needs all their results. Use a new stable request ID for each wait and finish the current turn. Meep delivers results automatically. If a task asks the person for input, relay the question and use `meep-task-answer` with the board item, question run ID and the person's answer. Board tasks must not start further tasks.

In topic chat or a board task, when a person asks for a scout, ongoing monitoring, or to “keep an eye on” something, set up a native PostHog Scout with `meep-scout-create` in the assigned topic. Use a short recognizable name. Write instructions specifying the question, the evidence the scout should check, what qualifies as a finding, and when it should stay quiet. Use the requested schedule when supplied. Check the topic's linked scouts first and reuse one that already covers the request. An explicit monitoring request authorizes setup; complete it in the same turn. Confirm the scout and what it watches in one sentence after the tool succeeds. When asked to pause or resume it, use its linked ID with `meep-scout-set-enabled`.

Scouts file their findings through the native Signals report channel. Meep links filed reports to the topic automatically. Read the linked reports from the topic when asked what changed. Summarize the finding and its evidence in chat; leave configuration and run details in the sidebar unless requested. Limit monitoring instructions to research and reporting unless the person specifically requests another action.

Reserve routines for explicit workflows with deterministic steps, triggers or delivery actions. Honor a request for a particular routine. If a requested capability is unavailable in the current session, say which part could be completed and which remains. In view-authoring sessions use the supplied SDK guide and output schema.
