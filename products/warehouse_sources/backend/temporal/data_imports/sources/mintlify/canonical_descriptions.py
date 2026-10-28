from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "assistant_conversations": {
        "description": "Individual user turns with assistant responses, referenced pages, and resolution status.",
        "docs_url": "https://www.mintlify.com/docs/api/analytics/assistant-conversations",
        "columns": {
            "id": "Identifier supplied by Mintlify for the conversation.",
            "timestamp": "Time when the user sent the message that started this turn.",
            "query": "Question that the user sent to the assistant.",
            "response": "Assistant answer or request for clarification.",
            "responseType": "Response type: answer or clarifying_question.",
            "sources": "Documentation pages that the response references.",
            "resolutionStatus": "Whether the assistant answered this turn.",
            "queryCategory": "Category that Mintlify assigned to the query, if available.",
            "feedback": "Positive or negative rating of the response, or null when no rating exists.",
            "pageUrl": "Documentation URL where the conversation started, if available.",
        },
    },
    "feedback": {
        "description": "User feedback from page ratings, code snippets, and agents, including its current review status.",
        "docs_url": "https://www.mintlify.com/docs/api/analytics/feedback",
        "columns": {
            "id": "Unique identifier for the feedback entry.",
            "path": "Path or URL of the document that received feedback.",
            "createdAt": "Time when the user submitted feedback, if available.",
            "comment": "Feedback text that the user submitted.",
            "source": "Origin of the feedback: code_snippet, contextual, agent, or thumbs_only.",
            "status": "Current review status: pending, in_progress, resolved, or dismissed.",
            "helpful": "Whether the user found the content helpful.",
            "contact": "Email address that the user supplied for a response.",
            "code": "Code snippet that received feedback.",
            "filename": "File name associated with the code snippet, if available.",
            "lang": "Programming language of the code snippet, if available.",
        },
    },
    "searches": {
        "description": "Search terms with aggregate counts and click statistics, ordered by search count in descending order.",
        "docs_url": "https://www.mintlify.com/docs/api/analytics/searches",
        "columns": {
            "searchQuery": "Search term that users entered.",
            "hits": "Number of searches for this term.",
            "ctr": "Percentage of searches for this term that led to a click on a specific result.",
            "topClickedPage": "Result path with the most clicks for this term, if available.",
            "lastSearchedAt": "Time of the most recent search for this term.",
        },
    },
    "views": {
        "description": "Content view counts for each documentation path, split by human and AI traffic.",
        "docs_url": "https://www.mintlify.com/docs/api/analytics/views",
        "columns": {
            "path": "Documentation page path.",
            "human": "Content views from human traffic.",
            "ai": "Content views from AI bot traffic.",
            "total": "Total content views for this path.",
        },
    },
    "visitors": {
        "description": "Approximate distinct visitors for each documentation path, split by human and AI traffic.",
        "docs_url": "https://www.mintlify.com/docs/api/analytics/visitors",
        "columns": {
            "path": "Documentation page path.",
            "human": "Distinct human visitors.",
            "ai": "Distinct AI bot visitors.",
            "total": "Approximate distinct visitors across human and AI traffic, with duplicates removed.",
        },
    },
}
