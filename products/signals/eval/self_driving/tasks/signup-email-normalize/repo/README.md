# acme-accounts

Account service for Acme apps: signup, login, and password reset. Stdlib only — no framework.

## Endpoints

- `POST /api/signup` — create an account (`{ "email", "password" }`)
- `POST /api/login` — authenticate (`{ "email", "password" }`)
- `POST /api/password-reset` — request a reset token (`{ "email" }`)

## Development

```
python -m acme_accounts.server
```

Set `POSTHOG_API_KEY` to enable product analytics capture.
