# acme-projects-api

REST API for listing Acme projects, consumed by customer integrations and the dashboard.

## Endpoints

- `GET /api/projects?page=&page_size=` — paginated project list. **Pages are 1-indexed**; `page_size` defaults to 20 and is capped at 100. Items are ordered by `createdAt` ascending.
- `GET /api/projects/:id` — fetch one project

## Development

```
npm install
npm start
```

Set `POSTHOG_API_KEY` to enable API analytics capture.
