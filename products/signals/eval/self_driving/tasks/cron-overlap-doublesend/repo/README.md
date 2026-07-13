# Acme Notifier

Sends the daily activity digest to every subscribed user. A scheduler ticks on
an interval and runs the digest job; the job collects due subscriptions,
renders each user's items, and sends the email.

## Running

```bash
npm install
npm start
```

The scheduler interval is configurable via `DIGEST_INTERVAL_MS` (default 1h).
Subscriptions and queued activity live in `data/` as JSON (a stand-in for the
subscriptions database).

## Layout

- `src/scheduler.js` - interval scheduler
- `src/digest.js` - the digest job (`runDigest`)
- `src/recipients.js` - recipient dedupe (users can subscribe via multiple projects)
- `src/store.js` - subscriptions + activity access
- `src/mailer.js` - SMTP mailer
- `src/config.js` - environment configuration
