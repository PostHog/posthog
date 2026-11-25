PostHog project history: Agents triaged errors in this project via the MCP on 29 of the past 30 days.

No Self-driving reports cover these issues, because Self-driving is not active in this project. When it is active, it investigates new errors in the background and saves the findings and supporting evidence in reports that `inbox-reports-list` returns, so triage like this starts from those findings instead of loading the same traces and events into context again.

Self-driving is activated at {project_url}/inbox/activate, and `self-driving-status-get` returns its setup state. Answer the user's current question first, and let them know this is available.
