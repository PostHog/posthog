from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from the Tavus API docs (https://docs.tavus.io/api-reference).
# Partial coverage is fine — uncovered columns fall back to LLM enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "videos": {
        "description": "A Tavus generated video — a rendered talking-head video produced from a script and a replica.",
        "docs_url": "https://docs.tavus.io/api-reference/video-request/get-videos",
        "columns": {
            "video_id": "The unique ID of the video.",
            "video_name": "The name given to the video.",
            "status": "The generation status of the video (e.g. queued, generating, ready, error).",
            "data": "The rendering data associated with the video, including scripts and settings.",
            "download_url": "The URL to download the rendered video, when ready.",
            "stream_url": "The URL to stream the rendered video, when ready.",
            "hosted_url": "The Tavus-hosted page URL for the video.",
            "status_details": "Additional detail about the current status, such as an error reason.",
            "created_at": "The timestamp when the video was created.",
            "updated_at": "The timestamp when the video was last updated.",
        },
    },
    "replicas": {
        "description": "A Tavus replica — a trained digital likeness used to generate personalized videos.",
        "docs_url": "https://docs.tavus.io/api-reference/replica-model/get-replicas",
        "columns": {
            "replica_id": "The unique ID of the replica.",
            "replica_name": "The name given to the replica.",
            "status": "The training status of the replica (e.g. started, training, ready, error).",
            "thumbnail_video_url": "The URL of a thumbnail preview video for the replica.",
            "training_progress": "The training progress of the replica.",
            "replica_type": "The type of replica (e.g. user, system).",
            "model_name": "The underlying model used for the replica.",
            "error_message": "The error message if replica training failed.",
            "created_at": "The timestamp when the replica was created.",
            "updated_at": "The timestamp when the replica was last updated.",
        },
    },
    "personas": {
        "description": "A Tavus persona — the conversational configuration (system prompt, layers, replica) for a CVI agent.",
        "docs_url": "https://docs.tavus.io/api-reference/personas/get-personas",
        "columns": {
            "persona_id": "The unique ID of the persona.",
            "persona_name": "The name given to the persona.",
            "system_prompt": "The system prompt that defines the persona's behavior.",
            "context": "The background context provided to the persona.",
            "default_replica_id": "The ID of the replica used by default for this persona.",
            "layers": "The configured conversational layers (e.g. transport, perception, STT, LLM).",
            "created_at": "The timestamp when the persona was created.",
            "updated_at": "The timestamp when the persona was last updated.",
        },
    },
    "conversations": {
        "description": "A Tavus conversation — a real-time Conversational Video Interface (CVI) session with a replica.",
        "docs_url": "https://docs.tavus.io/api-reference/conversations/get-conversations",
        "columns": {
            "conversation_id": "The unique ID of the conversation.",
            "conversation_name": "The name given to the conversation.",
            "status": "The status of the conversation (e.g. active, ended).",
            "conversation_url": "The URL used to join the conversation.",
            "callback_url": "The webhook URL that receives conversation event callbacks.",
            "replica_id": "The ID of the replica used in the conversation.",
            "persona_id": "The ID of the persona used in the conversation.",
            "created_at": "The timestamp when the conversation was created.",
            "updated_at": "The timestamp when the conversation was last updated.",
        },
    },
}
