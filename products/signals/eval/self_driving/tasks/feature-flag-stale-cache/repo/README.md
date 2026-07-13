# acme-config-service

Serves feature flag values (promo banner, maintenance mode, nav experiments) to storefront clients. Flag values come from the hosted flag provider configured via `FLAGS_SERVICE_URL`, with shipped defaults as fallback.

## Endpoints

- `GET /api/config` — current flag values for storefront clients
- `GET /api/banner` — rendered promo banner fragment (empty when disabled)

## Development

```
npm install
npm start
```

Set `FLAGS_SERVICE_URL` to point at the flag provider, and `POSTHOG_API_KEY` to enable analytics capture.
