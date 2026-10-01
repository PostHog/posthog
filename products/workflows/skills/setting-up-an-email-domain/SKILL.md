---
name: setting-up-an-email-domain
description: 'Set up a custom sending domain for PostHog Workflows email end to end: create the email sender, get its DNS records, publish them through Domain Connect or your own DNS tools, and verify until the domain can send. Use when asked to set up, connect, verify, or fix an email sender or sending domain for workflows, broadcasts, or campaigns, or when DNS records for SPF, DKIM, DMARC, or MAIL FROM are missing.'
---

# Setting up an email domain

Workflows sends email from the customer's own domain.
A sender (`hello@mail.example.com`) cannot send until its domain is verified, and verification needs DNS records the customer publishes at their DNS host.
Your job is to get from "I want to send email" to a verified sender with as little work for the person as possible.

## Tools

| Step                     | Tool                                           |
| ------------------------ | ---------------------------------------------- |
| Find existing senders    | `integrations-list` with `kind=email`          |
| Create the sender        | `integrations-email-create`                    |
| Get records, check them  | `integrations-email-verify-create`             |
| One-click DNS support?   | `integrations-domain-connect-check-retrieve`   |
| One-click DNS URL        | `integrations-domain-connect-apply-url-create` |
| Rename, change MAIL FROM | `integrations-email-partial-update`            |

Every step except the list and the check needs project admin access.
A 403 with "You don't have sufficient permissions in the project" means the person must ask a project admin; do not retry.

## Workflow

### 1. Pick the domain and the sender

Ask which domain to send from if the person has not said.
Recommend a subdomain such as `mail.example.com` or `updates.example.com`: it keeps marketing reputation and DMARC changes away from the root domain the company uses for everyday mail.
Accept the root domain if they prefer it.

If they only give a domain, default the sender to `hello@<domain>` with the company name as the display name, and tell them both can change later.
Free mailbox domains such as gmail.com are rejected, and so is a domain another PostHog organization already uses; relay that error and suggest contacting support for the second case.

Check `integrations-list` with `kind=email` first.
If a sender with the exact requested address exists, skip to step 3 with its `id` instead of creating it again.
A sender with a different address on the same domain still needs its own sender: create it in step 2.
It shares the domain's records, so step 3 usually reports them as `success` already.

### 2. Create the sender

Call `integrations-email-create` with `config.email` and `config.name`.
Leave `mail_from_subdomain` at its default `feedback` unless `feedback.<domain>` already has MX records (for example from another email tool); then pick another label such as `bounce`.
The returned `id` is the `integration_id` every other email tool takes.

### 3. Get the records

Call `integrations-email-verify-create`.
It returns `status` and `dnsRecords`; each record has `recordType`, `recordHostname` (fully qualified, or `@` for the sending domain itself), `recordValue`, an optional MX `priority`, and its own `status`.
Records with `status: success` are already in place.

### 4. Publish the records

Pick the first path that works:

1. **Domain Connect (the person approves at their DNS host).**
   Call `integrations-domain-connect-check-retrieve` with the sending domain.
   If `supported` is true, call `integrations-domain-connect-apply-url-create` with `context: email` and the `integration_id`, and omit `redirect_uri`.
   You cannot approve it yourself. Give the URL to the person and say what will happen: they sign in at their DNS host (for example Cloudflare), review the records and approve. Nothing changes until they approve.
2. **Your own DNS tools.**
   If you can manage the domain's DNS (a DNS provider MCP server, CLI or API you are authorized to use), add the missing records yourself.
   Read [references/publishing-records.md](references/publishing-records.md) first: it covers the records that must be merged, not duplicated.
3. **Hand the records to the person.**
   List only the records that are not `success`, as a table with type, name, value and priority.
   Mention that many DNS hosts append the domain to the name field, so they enter `_amazonses.mail` rather than `_amazonses.mail.example.com` when the zone is `example.com`.

Never create a second `_dmarc` record on any path.
If the domain already has one, the DMARC record shows as `success` with the existing value; keep it.

### 5. Verify until it succeeds

Call `integrations-email-verify-create` again after the records are published, then repeat with at least a minute between calls.
Each call checks DNS and the email provider, so do not call it in a tight loop.

- `success`: done. Every sender on this domain in the project can now send.
- `pending`: DNS is not visible yet, or a record is still missing. Compare the per-record statuses with what was published. DNS usually appears within minutes but can take up to 72 hours.
- `failed`: the provider stopped checking. Fix the records, then call verify again to restart the check.

After about 15 minutes of `pending` with every record published, stop polling.
Tell the person the remaining records are in place and propagating, and that they can ask you to check again later or watch the sender's status in PostHog.

### 6. Wrap up

Confirm the sender address and display name, and that it now appears as a sender option in workflows and broadcasts.
If the person wants another address on the same domain, create it with `integrations-email-create`, then call `integrations-email-verify-create` once for it.
The records are already in place, so it succeeds without new DNS work.

## Changing a sender

Use `integrations-email-partial-update` to change the display name or MAIL FROM subdomain.
Send the full config with the current `email`, which cannot change.
A new `mail_from_subdomain` needs new MX and SPF records at the new name, so run steps 3 to 5 again.
To change the address itself, create a new sender.
