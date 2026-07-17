# ReviewHog — glossary

Vocabulary settled while working on the product. Pure vocabulary — no spec, no implementation detail beyond what a term needs to be unambiguous.

- **Finding body** — the reviewer's description of a problem (`Issue.issue`, persisted as `ReviewIssueFinding.body`). Dual-audience text: it is rendered verbatim in the published comment AND consumed by three downstream LLM stages (the validator's `ISSUE` payload, dedup's fresh/prior finding payloads, and future turns' covered-findings block).
- **Validator argumentation** — the validator's why-valid / why-dismissed reasoning (`IssueValidation.argumentation`). For a *valid* finding it is presentation-only (humans + the copy-paste fix prompt); its only pipeline consumer is dedup's `prior_ruling`, and only when the finding was *dismissed*.
- **Published copy** — what humans read on GitHub (inline comment sections, report body) and in the Code review UI. Today it is byte-identical to the pipeline payload; nothing requires that.
- **Pipeline payload** — the same finding/verdict fields as consumed by downstream LLM stages (validator, dedup, covered-findings). The quality-critical audience.
- **Structural conciseness vs compression** — *structural*: the same information content reshaped into labeled bullets (claim / trigger / evidence / impact); *compression*: dropping information to save words. The no-quality-loss constraint rules out compression of pipeline payloads; it does not rule out restructuring.
- **Verify, don't restate** — the rule for validator argumentation: it is the *verification delta* (what was checked, what was found with file:line evidence, confirmed impact, priority rationale), never a restatement of the finding body's claim. Safe because no consumer — human or LLM — ever sees the argumentation without the body beside it.
