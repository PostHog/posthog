"""Derived product capability spec.

Computes, for every product, which surfaces it is usable from (web, MCP, Max AI,
self-driving, CLI, API, Slack, alerts) and which data sources feed it. Every fact is
derived from files that already exist in the repo — nothing here is hand-authored.

The output is published as a versioned JSON artifact for posthog.com to consume.
"""
