# acme-webhooks

Outbound webhook delivery for Acme platform events. Subscribers register an HTTPS endpoint and receive signed JSON payloads for the event types they subscribe to.

## Endpoints

- `POST /api/endpoints` — register a subscriber endpoint (`{ url, events }`), returns the signing secret
- `GET /api/endpoints` — list registered endpoints
- `POST /api/events` — publish a platform event, fanned out to matching endpoints

## Delivery semantics

Payloads are signed with HMAC-SHA256 (`x-acme-signature` header). Failed deliveries are retried up to `maxRetries` times.

## Development

```
npm install
npm start
```

Set `POSTHOG_API_KEY` to enable delivery analytics capture.
