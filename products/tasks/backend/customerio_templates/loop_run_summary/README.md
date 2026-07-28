# loop_run_summary Customer.io template

Source of truth for the "Desktop App - Loop run summary" transactional message in the PostHog Customer.io workspace (EU, environment 127208): message id 77, template id 3063, trigger name `loop_run_summary`. `CUSTOMER_IO_TEMPLATE_ID_MAP` in `posthog/email.py` maps `loop_run_summary` to this message. Edit these files, get review, then push with the commands below. Do not edit the template in the Customer.io UI.

## Rendering contract

`EmailMessage` runs every property through `sanitize_email_properties` (`posthog/email.py`) before they reach Customer.io as `message_data`, so inside this template:

- All `trigger.*` string values arrive HTML-escaped and URL-defanged. The body must interpolate them raw. Adding `| escape` double-escapes and shows entities like `&quot;` to recipients.
- The subject is plain text, so it must reverse the escaping. That is what the `replace` chain in `subject.liquid` does. Keep `&amp;` last.
- `*_url` keys are escaped but not defanged, so `trigger.run_url` works in an `href`. URLs inside `trigger.report` are defanged on purpose: readable, not clickable.
- Keep Liquid tags inside `<td>` content, never between table rows. HTML parsers hoist raw text out of tables, which breaks the Customer.io editor view.

Fields sent by `loop_notifications._send_email`: `loop_name`, `event_title`, `event_body`, `run_url`, `report`.

## Pushing changes

Uses the [Customer.io CLI](https://github.com/customerio/cli) authenticated against the PostHog account:

```bash
python3 -c "import json; print(json.dumps({'template': {'subject': open('subject.liquid').read().strip(), 'body': open('body.html').read()}}))" > /tmp/loop-template.json
cio api /v1/environments/127208/templates/3063 -X PUT --dry-run --json "$(cat /tmp/loop-template.json)"
cio api /v1/environments/127208/templates/3063 -X PUT --json "$(cat /tmp/loop-template.json)"
```

The local Django template `posthog/templates/email/loop_run_summary.html` is the SMTP fallback for self-hosted instances and renders from the unsanitized context with Django autoescape. It is a separate artifact; changing one does not change the other.
