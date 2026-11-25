---
name: working-with-meep
description: Find or create a private Meep topic and read its mission and linked task in PostHog.
---

Use `meep-topic-list` to find the topic in the current project. Use `meep-topic-get` to read its mission, goals, rules, facts and selected context before choosing PostHog tools for the question. Respect the topic rules when interpreting results and identify the underlying PostHog objects in the response. When a person requests a new responsibility, use `meep-topic-create` with their title and mission. Ask for the mission if it is unclear.

A topic's conversation ID identifies its persistent PostHog task. Reuse that task for follow-up work. A reference to an insight or flag is passive context. Set up monitoring only when the person asks for it.
