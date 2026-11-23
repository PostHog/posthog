# No imports, so registry.py and gate.py can both import the flags without an import cycle.
ISSUE_TAGS_FLAG = "error-tracking-issue-tags"
JEV_ISSUE_TAGS_FLAG = "error-tracking-issue-tags-jev"
# Off, the daily rule sweep counts the labels that it would write for the team and writes none.
RULE_SWEEP_WRITES_FLAG = "error-tracking-issue-tag-rule-sweep-writes"
