# Livestorm v1 endpoint inventory

The source sends a Livestorm API token in the `Authorization` header to `https://api.livestorm.co/v1`.
Connection setup uses [`GET /ping`](https://developers.livestorm.co/reference/get_ping) to check the token without a table scope.

| Table                   | GET path                                                                                                  | Token scope   | Row grain                       | Primary key        | Incremental candidate |
| ----------------------- | --------------------------------------------------------------------------------------------------------- | ------------- | ------------------------------- | ------------------ | --------------------- |
| `session_chat_messages` | [`/sessions/{id}/chat_messages`](https://developers.livestorm.co/reference/get_sessions-id-chat-messages) | Events read   | One chat message in one session | `session_id`, `id` | `updated_at`          |
| `session_questions`     | [`/sessions/{id}/questions`](https://developers.livestorm.co/reference/get_sessions-id-questions)         | `events:read` | One question in one session     | `session_id`, `id` | `updated_at`          |
| `team_members`          | [`/users`](https://developers.livestorm.co/reference/get_users-1)                                         | `admin:read`  | One workspace team member       | `id`               | `updated_at`          |
| `people_attributes`     | [`/people_attributes`](https://developers.livestorm.co/reference/get_people-attributes)                   | `admin:read`  | One workspace field definition  | `id`               | `updated_at`          |

All four endpoints return JSON:API lists in `data`.
Start `page[number]` at zero, set `page[size]` to 50, and stop after `meta.page_count` pages.
The session tables read `/sessions` first and request each session's list separately.
The chat reference does not name a route-specific scope. The source groups it with the Events tables.

All four tables use full refresh. The API does not document an update filter for these routes.
The tables are off by default to avoid extra API calls or permission errors on existing connections.
