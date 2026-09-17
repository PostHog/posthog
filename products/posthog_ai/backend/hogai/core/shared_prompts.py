CORE_MEMORY_PROMPT = """
You have access to the core memory about the user's company and product in the <core_memory> tag. Use this memory in your thinking.
<core_memory>
{{{core_memory}}}
</core_memory>
""".strip()

HYPERLINK_USAGE_INSTRUCTIONS = """
\n\n<system_reminder>The results contain URLs to specific entities. When presenting them to the user, use hyperlinks and Markdown formatting.</system_reminder>"""
