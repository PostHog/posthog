# Judge prompt (one report)

You are judging one report filed by an automated code-reading scout. The report claims an API contract defect in the PostHog repository at commit {commit}. Your checkout is at that commit. You have read access to the project's inbox and memory through the PostHog MCP.

Answer every rubric item below with yes, no or unsure, plus one sentence of evidence with a file path and line range. Judge from the code, never from the report's own confidence. If you cannot open the file, answer unsure.

Rubric items: P1 traced, P2 evidence, O1 real, O2 in scope, O3 fix direction, O4 severity, O5 not a duplicate. Definitions are in rubric-v0.md, quoted below.

The scout's rules (its discriminator and noise list) are quoted below; apply them literally for O2 and O4.

Report:
{report_json}

Return JSON: {"P1":{"verdict":..,"evidence":..}, ..., "O5":{...}, "endpoint":"<route or path>", "defect_kind":"pagination|search|list-cost|scope|other"}
