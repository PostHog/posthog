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
}
