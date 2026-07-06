### Tool search

**Always prefer `search` over `tools`** — `tools` returns every tool and wastes tokens. Use `search <query>` to find what you need.

`search` understands two kinds of query:

- **Plain words** (including multiple words / natural language) — ranked by relevance across tool name, title, and description, with name matches weighted highest. `search create dashboard insight` surfaces `dashboard-create` / `insight-create` at the top. Results are capped to the top matches; narrow the query if you see a truncation note.
- **Regex** — a query containing regex metacharacters (`- | ( ) [ ] \ . * + ^ $ ?`) is treated as a single case-insensitive regular expression, matched against name/title/description. Use this for precise, narrow patterns.

**Good queries:**

- `search create dashboard insight` — plain words, ranked: dashboard/insight creation tools first
- `search feature-flag` — regex (`-`): tools for feature flags
- `search dashboard` — dashboard CRUD tools
- `search query-` — regex (`-`): all insight query tools
- `search experiment` — experiment tools
- `search survey` — survey tools

**Avoid queries that are too broad** (match dozens of tools):

- `search data` — matches almost everything
- `search get list create` — action verbs across all domains
- `search pageview|email@address.com` — unrelated to tools

Only fall back to `tools` if you have no idea which domain to search, or if `search` returns no results.

PostHog tools have lowercase kebab-case naming. Tools are organized by category:

{tool_domains}
Typical action names: list/retrieve/get/create/update/delete/query.
Example tool names: execute-sql, experiment-create, feature-flag-get-all.
