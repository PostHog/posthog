### Tool search

**Always prefer `search` over `tools`** — `tools` returns every tool and wastes tokens. Use `search <regex>` with a short, targeted pattern to find what you need.

Write focused patterns that match 1-5 tools. The regex matches against tool name, title, and description.

**Good patterns** (specific, narrow):

- `search feature-flag` — tools for feature flags
- `search dashboard` — dashboard CRUD tools
- `search query-` — all insight query tools
- `search experiment` — experiment tools
- `search survey` — survey tools

**Bad patterns** (too broad, match dozens of tools):

- `search data` — matches almost everything
- `search get|list|create` — matches action verbs across all domains
- `search pageview_trends` — search is too focused
- `search pageview|email@address.com` — unrelated to tools

Only fall back to `tools` if you have no idea which domain to search, or if `search` returns no results.

PostHog tools have lowercase kebab-case naming. Tools are organized by category:

{tool_domains}
Typical action names: list/retrieve/get/create/update/delete/query.
Example tool names: execute-sql, experiment-create, feature-flag-get-all.
