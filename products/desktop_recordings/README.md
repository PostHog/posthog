# Desktop Recordings Product

Backend API for recording desktop meetings via Array desktop app using Recall.ai.

## Setup

### Environment Variables

```bash
RECALL_AI_API_KEY=your-recall-ai-api-key
RECALL_AI_API_URL=https://us-west-2.recall.ai  # Optional, defaults to this
```

## API Endpoints

### Create Upload Token

```bash
POST /api/environments/{team_id}/desktop_recordings/
Authorization: Bearer {personal_api_key}
Content-Type: application/json

{
  "platform": "zoom"  # or "teams", "meet", "slack", "desktop_audio"
}

Response:
{
  "upload_token": "...",  # Pass to Recall SDK
  "id": "..."   # PostHog recording ID
  ...additional fields...
}
```

### List Recordings

```bash
GET /api/environments/{team_id}/desktop_recordings/
Authorization: Bearer {personal_api_key}

Query params:
- platform: Filter by platform (zoom, teams, meet, etc.)
- status: Filter by status (recording, uploading, processing, ready, failed)
- search: Search transcript text
```

### Get Recording Details

```bash
GET /api/environments/{team_id}/desktop_recordings/{id}/
Authorization: Bearer {personal_api_key}
```

### Get Transcript

```bash
GET /api/environments/{team_id}/desktop_recordings/{id}/transcript/
Authorization: Bearer {personal_api_key}

Response:
{
  "full_text": "Complete transcript...",
  "segments": [
    {
      "text": "...",
      "start": 0,
      "end": 5,
      "speaker": "Speaker 1"
    }
  ],
  "extracted_tasks": [
    {
      "title": "Fix login bug",
      "description": "Users can't log in on Safari",
      "assigned_to": "John"
    }
  ]
}
```

## Personal API Key Scopes

Users need to create a Personal API Key with these scopes:

- `desktop_recording:read` - View recordings and transcripts
- `desktop_recording:write` - Create new recordings

## Architecture

### Data Flow

1. Array desktop detects meeting → calls `create_upload`
2. PostHog creates recording → returns Recall upload token
3. Array uses Recall SDK to record → uploads to Recall
4. Once upload is done, Array updates the desktop recording on PostHog
5. Recording status changes to "ready"

### Models

- `DesktopRecording`: Stores recording metadata, status, video URL
- `RecordingTranscript`: Stores transcript text, segments, extracted tasks

### Webhook Events

- `sdk_upload.uploading`: Recording started uploading
- `sdk_upload.complete`: Upload finished, triggers processing
- `sdk_upload.failed`: Upload failed

## Testing

```bash
# Run backend tests
python -m pytest products/desktop_recordings/backend/tests/ -v

# Test API endpoint
curl -X POST 'http://localhost:8010/api/environments/1/desktop_recordings/' \
  -H 'Authorization: Bearer phx_YOUR_API_KEY' \
  -H 'Content-Type: application/json' \
  -d '{"platform": "zoom"}'
```

## Next Steps (Phase 2)

- Web UI to view recordings in PostHog
- Integration with PostHog Tasks product
- Team permissions and sharing
- Search across all transcripts
