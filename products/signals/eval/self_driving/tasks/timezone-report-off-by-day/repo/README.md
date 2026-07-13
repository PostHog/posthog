# Acme Reports

Daily summary reports for Acme Commerce merchants: every evening each account
gets an email with the day's order count and revenue.

Pure-stdlib Python service. Order data comes from the commerce database
(represented here by `store.InMemoryStore`); each account has an IANA timezone
picked at signup.

## Running

```bash
python -m acme_reports.cli
```

Generates and "emails" (prints) the daily report for every sample account.

## Layout

- `acme_reports/models.py` - `Account`, `Order`, `DailyReport`
- `acme_reports/store.py` - order/account access
- `acme_reports/reports.py` - report generation
- `acme_reports/emailer.py` - email rendering and sending
- `acme_reports/analytics.py` - PostHog capture (stdlib HTTP)
- `acme_reports/cli.py` - entry point
