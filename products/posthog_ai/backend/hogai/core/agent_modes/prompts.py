ROOT_HARD_LIMIT_REACHED_PROMPT = """
You have reached the maximum number of iterations, a security measure to prevent infinite loops. Now, summarize the conversation so far and answer my question if you can. Then, ask me if I'd like to continue what you were doing.
""".strip()

ROOT_TOOL_DOES_NOT_EXIST = """
This tool does not exist.
<system_reminder>
Only use tools that are available to you.
</system_reminder>
""".strip()

ROOT_AGENT_MODE_REMINDER_PROMPT = """
<system_reminder>
You are currently in {mode} mode. This mode was enabled earlier in the conversation.
</system_reminder>
""".strip()

ROOT_CONVERSATION_SUMMARY_PROMPT = """
This session continues from a prior conversation that exceeded the context window. A summary of that conversation is provided below:
{summary}
""".strip()

ROOT_TODO_REMINDER_PROMPT = """
{{{todo_content}}}

<system_reminder>The above is your latest generated todo list. Use it to continue your work.</system_reminder>
""".strip()
