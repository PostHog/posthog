"""CI signal detection + emission for engineering_analytics.

Deterministic detectors run the curated PR/CI read layer (the same ``logic`` that backs the MCP
read tools) on a schedule, turn threshold conditions into typed ``CISignalFinding`` objects, and
emit them into the Signals product via its facade (``emit_signal``). PostHog Code then groups,
researches, and — when a finding carries actionable remediation — autonomously opens a fix PR.

Detection is defined once here so the emitter and the read surface never diverge (SPEC §7).
"""
