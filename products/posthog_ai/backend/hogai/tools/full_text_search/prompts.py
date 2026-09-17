FOUND_ENTITIES_PROMPT = """
Successfully found {{{total_results}}} entities matching the user's query.

{{{entities_list}}}
""".strip()

ENTITY_TYPE_SUMMARY_PROMPT = """
**Results by type:**
{{{entity_type_summary}}}
""".strip()

NO_SEARCH_QUERY_PROVIDED_PROMPT = """
No search query was provided.
""".strip()

INVALID_ENTITY_KIND_PROMPT = """
Invalid entity kind: {{{kind}}}. Please provide a valid entity kind for the tool.
""".strip()

NO_ENTITIES_FOUND_PROMPT = """
No entities found matching the query '{{{query}}}' for entity types.
<system_reminder>
You may try again with a rewritten query, or use the `list_data` tool to paginate through entities.
</system_reminder>
""".strip()
