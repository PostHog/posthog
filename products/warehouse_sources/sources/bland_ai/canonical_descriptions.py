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
    "sms_conversations": {
        "description": (
            "A messaging conversation handled by a Bland AI agent over SMS, RCS or WhatsApp. One row "
            "per conversation, with the numbers involved, the pathway driving it, and the outcome. "
            "Message bodies live in the sms_messages table."
        ),
        "docs_url": "https://docs.bland.ai/api-v1/get/sms-conversations",
        "columns": {
            "id": "The unique identifier of the conversation.",
            "created_at": "The timestamp when the conversation was created.",
            "updated_at": "The timestamp when the conversation was last updated.",
            "user_number": "The user-facing phone number in the conversation.",
            "agent_number": "The assistant's phone number in the conversation.",
            "variables": "Arbitrary variables associated with the conversation.",
            "current_node_id": "The identifier of the current node in the conversational pathway.",
            "curr_pathway_id": "The identifier of the pathway currently driving the conversation.",
            "curr_pathway_version": "The version of the pathway currently driving the conversation.",
            "timed_out_at": "The timestamp when the conversation timed out due to inactivity, if it did.",
            "is_active": "Whether the conversation is still active.",
            "message_count": "The number of messages in the conversation.",
            "last_message": "The content of the most recent message.",
            "last_message_at": "The timestamp of the most recent message.",
            "pathway_tags": "Tags from the pathway nodes visited during the conversation.",
            "effective_channel": "The resolved delivery channel: sms, rcs, or whatsapp.",
            "summary": "AI-generated summary of the conversation, if a summary prompt was configured.",
            "citation_variables": "Citation variable values extracted from the conversation, if citation schemas were configured.",
            "disposition_tag": "The first successful outcome result tag, if outcomes were configured.",
        },
    },
    "sms_messages": {
        "description": (
            "A single message sent or received during a Bland AI messaging conversation. One row per "
            "message, joined to the sms_conversations table via conversation_id. Fetched from the "
            "per-conversation detail endpoint since the conversation list returns only a message count."
        ),
        "docs_url": "https://docs.bland.ai/api-v1/get/sms-conversations-id",
        "columns": {
            "id": "The identifier of the message within the conversation.",
            "created_at": "The timestamp when the message was created.",
            "message": "The message body.",
            "from": "The sending phone number.",
            "to": "The receiving phone number.",
            "sender": "Who sent the message: USER or AGENT.",
            "status": "Delivery status of the message: pending, queued, sent, delivered, read, failed, or undelivered.",
            "error_code": "The Twilio error code if the message failed.",
            "conversation_id": "The unique identifier of the conversation this message belongs to.",
            "conversation_created_at": "The timestamp when the parent conversation was created.",
        },
    },
    "inbound_numbers": {
        "description": (
            "An inbound phone number configured on your Bland AI account, with the agent settings that "
            "apply to calls it receives."
        ),
        "docs_url": "https://docs.bland.ai/api-v1/get/inbound",
        "columns": {
            "phone_number": "The inbound phone number.",
            "created_at": "The timestamp when the number was added to the account.",
            "prompt": "The prompt the agent follows when the number receives a call.",
            "webhook": "The URL called with the call details once a call on this number ends.",
            "voice_id": "The voice the agent uses on calls to this number.",
            "dynamic_data": "API requests the agent makes mid-call on this number.",
            "interruption_threshold": "How long the agent waits before treating the caller as interrupting.",
            "first_sentence": "The sentence the agent opens the call with.",
            "reduce_latency": "Whether latency reduction is enabled for calls to this number.",
            "transfer_phone_number": "The number calls are transferred to when the agent hands off.",
            "voice_settings": "Synthesis overrides applied to the agent's voice on this number.",
            "record": "Whether calls to this number are recorded.",
            "max_duration": "The maximum length a call to this number may last, in minutes.",
        },
    },
    "personas": {
        "description": (
            "A persona in your Bland AI organization — a reusable agent identity that phone numbers "
            "attach to, carrying its own prompts, pathway routing, and call configuration."
        ),
        "docs_url": "https://docs.bland.ai/api-v1/get/personas",
        "columns": {
            "id": "The unique identifier of the persona.",
            "name": "The display name of the persona.",
            "role": "The role assigned to the persona.",
            "description": "A description of the persona's purpose.",
            "tags": "Tags associated with the persona.",
            "image_url": "The URL of the persona's profile image.",
            "created_at": "The timestamp when the persona was created.",
            "updated_at": "The timestamp when the persona was last modified.",
            "deleted_at": "The timestamp when the persona was deleted, or null while it is active.",
            "user_id": "The identifier of the user who owns the persona.",
            "current_production_version_id": "The identifier of the persona's current production version.",
            "current_draft_version_id": "The identifier of the persona's current draft version.",
            "inbound_numbers": "The inbound phone numbers attached to the persona.",
            "current_production_version": "The full production version object, including its prompts, pathway conditions, and call config.",
            "current_draft_version": "The full draft version object, in the same shape as the production version.",
        },
    },
    "voices": {
        "description": (
            "A voice your Bland AI account can use on calls: a Bland curated voice, a voice you cloned, "
            "or one added from the public library. Resolves the voice_id referenced by calls."
        ),
        "docs_url": "https://docs.bland.ai/api-v1/get/voices",
        "columns": {
            "id": "The unique identifier of the voice, passed as voice_id when sending a call.",
            "name": "The display name of the voice.",
            "description": "A short human-readable description of the voice.",
            "public": "True for shared library and Bland curated voices, false for voices private to your organization.",
            "tags": "Labels describing the voice, such as language, style, and source.",
            "user_id": "The identifier of the owner, or null for Bland curated voices.",
            "voice_id": "The underlying model identifier. The format varies by engine.",
            "service": "The synthesis engine: BTTS, BTTS_V2, BTTS_V3, or LEGACY.",
            "finetuned": "Whether the voice has been fine-tuned past the base clone.",
            "is_creator_voice": "Whether the voice is in the Bland creator program, which may add a per-character fee.",
            "ratings": "The total number of ratings the voice has received.",
            "total_ratings": "Alias of ratings, returned for backwards compatibility.",
            "average_rating": "The average rating of the voice, from 0 to 5.",
            "my_rating": "Your own rating for the voice, or null if you have not rated it.",
            "creator_display_name": "The creator's name for voices in the creator program.",
        },
    },
    "call_events": {
        "description": (
            "A single event logged during a Bland AI call, from the call's event stream. One row per "
            "event, joined to the calls table via call_id."
        ),
        "docs_url": "https://docs.bland.ai/api-v1/get/event-stream",
        "columns": {
            "call_id": "The unique identifier for the call.",
            "event_index": "The position of the event in the call's event stream, starting at 0.",
            "call_created_at": "The creation time of the parent call.",
            "level": "The level of the event: queue or call.",
            "message": "The message of the event.",
            "category": "The category of the event: info, performance or error.",
            "timestamp": "When the event occurred.",
        },
    },
    "web_agents": {
        "description": "A web agent: a voice agent that talks to visitors in a browser instead of over the phone.",
        "docs_url": "https://docs.bland.ai/api-v1/get/agents",
        "columns": {
            "agent_id": "The unique identifier for the agent.",
            "webhook": "The webhook URL for the agent.",
            "dynamic_data": "Dynamic data objects the agent loads.",
            "interruption_threshold": "The threshold for agent interruption.",
            "first_sentence": "The first sentence the agent will say.",
            "model": "The model used by the agent.",
            "voice_settings": "The voice settings for the agent.",
            "voice": "The voice used by the agent.",
            "prompt": "The prompt for the agent.",
            "temperature": "The temperature setting for the agent.",
            "max_duration": "The maximum call duration for the agent.",
            "language": "The language used by the agent.",
            "tools": "The custom tools the agent can use.",
        },
    },
    "pathway_versions": {
        "description": "A version of a conversational pathway. Joined to the pathways table via pathway_id.",
        "docs_url": "https://docs.bland.ai/api-v1/get/pathway_versions",
        "columns": {
            "pathway_id": "The ID of the pathway this version belongs to.",
            "id": "The unique identifier of the pathway version.",
            "version_number": "The version number of this pathway version.",
            "created_at": "The timestamp when this version was created.",
            "name": "The name of this pathway version.",
            "is_latest": "Whether this is the latest version of the pathway.",
        },
    },
    "eval_runs": {
        "description": "An eval run: a batch of calls scored by one or more LLM judges (eval agents).",
        "docs_url": "https://docs.bland.ai/api-v1/get/evals-runs",
        "columns": {
            "id": "Unique identifier for the eval run.",
            "status": "Current status of the run: PENDING, QUEUED, RUNNING, COMPLETE, PARTIAL, FAILED or CANCELLED.",
            "triggered_by": "How the run was triggered: manual, auto or backfill.",
            "run_mode": "The scoring modality used: text, audio or full.",
            "resolved_call_count": "Number of calls resolved for the run.",
            "resolved_agent_count": "Number of eval agents resolved for the run.",
            "resolved_atom_count": "Total number of call-by-agent evaluations in the run.",
            "completed_atom_count": "Number of evaluations that have completed.",
            "summary": "Aggregate scoring summary for the run, or null if not yet available.",
            "billable_cost_usd": "Billable cost for this run in USD.",
            "workbench_setup_id": "The workbench setup the run was started from, if any.",
            "workbench_setup_version_id": "The pinned workbench setup version used, if any.",
            "metadata": "Key-value metadata attached to the run.",
            "created_at": "ISO 8601 timestamp when the run was created.",
            "started_at": "ISO 8601 timestamp when the run started, or null if not yet started.",
            "completed_at": "ISO 8601 timestamp when the run completed, or null if not yet complete.",
        },
    },
    "eval_call_results": {
        "description": (
            "The result of scoring one call in an eval run. Joined to eval_runs via eval_run_id and to "
            "calls via call_id."
        ),
        "docs_url": "https://docs.bland.ai/api-v1/get/evals-runs-id-call-results",
        "columns": {
            "id": "Unique identifier for this call result.",
            "org_id": "The organization that owns this result.",
            "eval_run_id": "The eval run this result belongs to.",
            "call_id": "The ID of the call that was scored.",
            "call_display_name": "Display name of the call, if available.",
            "call_started_at": "ISO 8601 timestamp when the call started.",
            "call_duration_seconds": "Duration of the call in seconds.",
            "call_ended_by": "Which party ended the call.",
            "transcript_snapshot_ref": "Reference to the transcript snapshot used for scoring.",
            "transcript_snapshot_expires_at": "ISO 8601 timestamp when the transcript snapshot expires.",
            "status": "Status of this call's evaluation: PENDING, QUEUED, RUNNING, COMPLETE, FAILED or INSUFFICIENT_EVIDENCE.",
            "started_at": "ISO 8601 timestamp when scoring started for this call.",
            "completed_at": "ISO 8601 timestamp when scoring completed for this call.",
            "overall_score_normalized_0_100": "Overall weighted score for this call, normalized 0-100.",
            "text_score_normalized_0_100": "Text-modality score for this call, normalized 0-100.",
            "audio_score_normalized_0_100": "Audio-modality score for this call, normalized 0-100.",
            "failed_agent_count": "Number of agent evaluations that failed for this call.",
            "insufficient_evidence_agent_count": "Number of agent evaluations that returned insufficient evidence.",
            "agent_results": "Per-agent verdicts for this call. Empty, because the sync does not request them inline.",
            "created_at": "ISO 8601 timestamp when this call result was created.",
        },
    },
}
