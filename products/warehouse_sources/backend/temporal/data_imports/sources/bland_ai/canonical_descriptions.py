from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "calls": {
        "description": (
            "A phone call dispatched or received by your Bland AI account, with status, timing, cost, "
            "and post-call analysis metadata. Transcripts are excluded from this table for size reasons — "
            "sync the call_transcripts table for those."
        ),
        "docs_url": "https://docs.bland.ai/api-v1/get/calls-id",
        "columns": {
            "call_id": "The unique identifier for the call.",
            "created_at": "The timestamp for when the call request was created.",
            "started_at": "The time the call was connected.",
            "end_at": "The time the call will automatically be ended at if still connected (because of max_duration).",
            "call_length": "The length of the call in minutes.",
            "to": "The phone number that received the call.",
            "from": "The phone number that made the call.",
            "completed": "Whether the call has been completed.",
            "inbound": "Whether the call was inbound or outbound. False for outbound calls.",
            "queue_status": "The status of the call (new, queued, allocated, started, complete, or an error stage).",
            "error_message": "The error recorded if the call failed at any stage.",
            "answered_by": "Who answered the call (e.g. human, voicemail).",
            "batch_id": "If the call is part of a batch, its batch_id.",
            "campaign_id": "If the call is part of a campaign, its campaign id.",
            "max_duration": "The maximum length of time the call was allowed to last, in minutes.",
            "endpoint_url": "The URL of the deployment that handled the call.",
            "transferred_to": "Number that the person was transferred to.",
            "transferred_at": "The timestamp when the call was transferred to another number.",
            "request_data": "Details about parameters in the original API request.",
            "variables": "Variables extracted or injected during the call.",
            "record": "Whether the call was recorded.",
            "recording_url": "URL of the call recording, if recording was enabled.",
            "metadata": "Arbitrary metadata attached to the call at dispatch time.",
            "summary": "AI-generated summary of the call.",
            "price": "The cost of the call.",
            "local_dialing": "Whether local dialing was used for the call.",
            "call_ended_by": "Which party ended the call.",
            "pathway_id": "The conversational pathway that drove the call, if any.",
            "pathway_logs": "Logs from the pathway execution.",
            "pathway_version": "The version of the pathway used for the call.",
            "analysis_schema": "The schema requested for post-call analysis.",
            "analysis": "Post-call analysis results.",
            "status": "The current status of the call.",
            "corrected_duration": "The corrected duration of the call.",
            "citations": "Citations extracted from the call.",
            "voice_id": "The voice used by the agent on the call.",
        },
    },
    "call_transcripts": {
        "description": (
            "A single utterance spoken during a Bland AI call. One row per phrase, joined to the calls "
            "table via call_id. Fetched from the per-call detail endpoint since the call list excludes "
            "transcripts for size reasons."
        ),
        "docs_url": "https://docs.bland.ai/api-v1/get/calls-id",
        "columns": {
            "id": "The identifier of the transcript utterance within the call.",
            "created_at": "The timestamp when the utterance was spoken.",
            "text": "The text of the utterance.",
            "user": "Who spoke the utterance: user, assistant, robot, or agent-action.",
            "call_id": "The unique identifier of the call this utterance belongs to.",
            "call_created_at": "The timestamp when the parent call request was created.",
        },
    },
    "pathways": {
        "description": (
            "A conversational pathway in your Bland AI account — the node/edge graph that gives the "
            "agent structured control over dialogue, branching, and actions."
        ),
        "docs_url": "https://docs.bland.ai/api-v1/get/all_pathway",
        "columns": {
            "id": "The unique identifier of the pathway.",
            "name": "The name of the conversational pathway.",
            "description": "A description of the conversational pathway.",
            "nodes": "Data about all the nodes in the pathway.",
            "edges": "Data about the connections between nodes, including the labels and conditions for taking each edge.",
        },
    },
}
