# Legal documents — next steps

## Context

Today's flow, end-to-end:

1. User submits the form at `/legal/new/:type`.
2. `LegalDocumentViewSet.perform_create` persists the row with a random `webhook_secret` and fires a PostHog event (`submitted BAA` / `clicked Request DPA`) with all form fields plus the secret.
3. **Zapier** listens on that PostHog event → builds a PandaDoc envelope → sends it to the customer.
4. PandaDoc emails the signing envelope; customer counter-signs.
5. **Zapier** is configured with a second step: when the envelope completes, POST the download URL back to
   `POST /api/legal_documents/<id>/signed` with the pre-shared secret and the signed URL. Our public webhook
   validates the secret via `hmac.compare_digest` and flips `status` to `signed`.

This works but has two Zapier Zaps in the critical path we don't own, and the secret round-trip is only necessary
because we don't have a first-class identifier that both sides already agree on. The plan below replaces both Zaps
with direct integrations we own and simplifies the authentication story.

## Goal

- Remove Zapier from the picture — we own both sides of the PandaDoc lifecycle.
- Keep the existing internal notification flow with
  customer context from Vitally (most importantly TAM — the assigned account manager — and ARR) and drop it into
  Slack so the right humans see new BAA/DPA submissions as they happen.
- Simplify the signed-URL callback: PandaDoc already gives every envelope a document ID. Store that ID on our row,
  authenticate incoming PandaDoc webhooks with PandaDoc's native HMAC signature, and skip the ad-hoc secret.

## Approach

Three new outbound integrations on submit (PandaDoc, Vitally, Slack) and one inbound PandaDoc webhook. All behind a
feature flag so we can roll this out while Zapier keeps running, then flip the flag and decommission the Zaps.

### 1. Outbound: create PandaDoc envelope

New module `products/legal_documents/backend/integrations/pandadoc.py`:

- Thin `PandaDocClient` around `requests` — no SDK needed, the public API surface we use is small.
- `create_document_from_template(template_id, name, recipients, tokens) -> {id, status, public_url}` hitting
  `POST https://api.pandadoc.com/public/v1/documents` with `Authorization: API-Key {PANDADOC_API_KEY}`.
- `send_document(document_id, subject, message)` → `POST /public/v1/documents/{id}/send`.
- Template-ID constants: `PANDADOC_BAA_TEMPLATE_ID`, `PANDADOC_DPA_PRETTY_TEMPLATE_ID`,
  `PANDADOC_DPA_LAWYER_TEMPLATE_ID`. Tokens required on each template:
  `company_name`, `company_address` (DPA), `representative_name`, `representative_title`, `representative_email`.

On the model:

- Add `pandadoc_document_id = models.CharField(max_length=64, blank=True, db_index=True)` — unique per row, empty
  until the PandaDoc call succeeds.
- Drop `webhook_secret` once we're fully off Zapier (covered in "Migration" below).

In `LegalDocumentViewSet.perform_create`, replace the current `_fire_zapier_event` call with:

1. `client.create_document_from_template(...)` with the template + token map.
2. `client.send_document(...)` to dispatch the signing email.
3. Persist the returned PandaDoc ID on the row.
4. Enqueue a Celery task to post the internal Slack notification (see below). Don't block the user's submit on the
   Slack + Vitally round-trip.

If the PandaDoc call fails, we 502 the submit and leave the row without a PandaDoc ID — retryable, and easy to
re-trigger from the admin by adding a "Resend envelope" admin action later.

### 2. Vitally lookup for TAM / ARR

New `products/legal_documents/backend/integrations/vitally.py`:

- `get_account_by_domain(domain) -> {tam_email, tam_name, arr_usd, health_score, ...} | None`.
- Auth: `Authorization: Basic {base64(VITALLY_API_TOKEN:)}` against
  `GET https://api.vitally.io/resources/v1/accounts?externalId=<domain>` (or however we key accounts — confirm
  with RevOps; the current convention is likely org primary domain or Stripe customer ID).
- Cache hits for 15 minutes with a Redis key keyed on the domain to avoid hammering Vitally if a customer spams the
  form.
- Return `None` on 404 / 5xx / timeout — never block submit on Vitally being unhealthy. The Slack message still goes
  out; it just won't include TAM context.

### 3. Slack notification

New `products/legal_documents/backend/integrations/slack.py` (or reuse the existing helper used by
`products/conversations/backend/slack.py` — check first).

- Channel: `#legal-document-submissions` (new — ask #team-ops to create it).
- Message payload (Block Kit):
  - Header: `:scroll: New {BAA | DPA} submitted`
  - Fields block with `Company`, `Representative`, `Representative email`, `Org in PostHog`, `TAM`, `ARR`
    (the last two come from Vitally; fall back to `Unknown` if the lookup missed).
  - Action row with a link to the PandaDoc envelope (`https://app.pandadoc.com/a/#/documents/{pandadoc_document_id}`)
    and a link back to the org's billing page in PostHog.
- Fire from a Celery task so a flaky Slack API doesn't slow down submission or hold a DB transaction.
- Use `ph_scoped_capture` instead of `posthoganalytics.capture` if we also want to capture a PostHog event
  from the task — AGENTS.md warns that the latter is silently dropped in Celery.

### 4. Inbound: PandaDoc webhook on envelope completion

Replace the current `legal_document_signed_webhook`:

- PandaDoc configurable webhook → `POST /api/legal_documents/pandadoc_webhook` (no `<id>` in the path; we look up
  the row by the PandaDoc-provided `data[0].id`).
- PandaDoc signs every webhook with HMAC-SHA256 over the raw body using a shared key we configure in the PandaDoc
  dashboard. Verify via `hmac.compare_digest(expected, request.headers["X-Pandadoc-Signature"])` where
  `expected = hmac.new(PANDADOC_WEBHOOK_SECRET, request.body, hashlib.sha256).hexdigest()`.
- Event we care about: `document_state_changed` with `data[0].status == "document.completed"`. Ignore all other
  events.
- Look up the row by `pandadoc_document_id`; 404 if unknown (never signal which IDs exist).
- Pull the signed PDF's download URL via `GET /public/v1/documents/{id}/download/?watermark=false`. PandaDoc
  returns a transient URL that expires after a few hours — fine for our "signed copy" link; we re-fetch on demand
  via a small detail endpoint (see "Frontend" below), or mirror to S3 for a stable link (nice-to-have).
- Keep the existing `IPThrottle` classes (`5/minute` burst, `30/hour` sustained) — PandaDoc won't exceed them in
  normal operation, and they cap abuse if the HMAC secret ever leaks.

### 5. Frontend changes

- Download link stays the same `signed_document_url`, but if we don't persist a URL (option A from #4) we expose a
  `GET /api/organizations/:org_id/legal_documents/:id/download` detail endpoint that re-fetches a fresh URL from
  PandaDoc and redirects. No other UI changes.
- Optionally surface the PandaDoc envelope status (draft / sent / viewed / completed) as a richer `LemonTag` on the
  list. This maps 1:1 to PandaDoc's `document.*` enum.

### 6. Config surface

New settings in `posthog/settings/web.py` (read from env):

- `PANDADOC_API_KEY`
- `PANDADOC_WEBHOOK_SECRET`
- `PANDADOC_BAA_TEMPLATE_ID`, `PANDADOC_DPA_PRETTY_TEMPLATE_ID`, `PANDADOC_DPA_LAWYER_TEMPLATE_ID`
- `VITALLY_API_TOKEN`
- `SLACK_LEGAL_DOCUMENTS_CHANNEL_ID` (or hardcode if the channel is stable)
- The existing Slack bot token our workspace already uses is reused — no new OAuth app.

## Migration

Three-phase rollout, dual-write during phase 2 so we can compare and flip back if anything misbehaves.

**Phase 1 — add PandaDoc + Vitally + Slack behind a feature flag.**
`feature_flags.LEGAL_DOCUMENTS_OWNED_PANDADOC`. Default off. Do all the new outbound work on submit only when the
flag is on for the target org. Add the new inbound webhook URL and accept events but don't migrate old rows.

**Phase 2 — dual-run.**
Flip the flag on for our own org first, then a handful of friendly orgs, then 100%. While both paths are live:

- The old Zapier Zap still creates PandaDocs for flag-off orgs; the new code path does it for flag-on orgs.
- The old signed-URL callback still works for rows that don't have a `pandadoc_document_id`. The new PandaDoc
  webhook takes over for rows with one.
- Keep `webhook_secret` populated on new rows for safety.

**Phase 3 — decommission Zapier.**

- Disable both Zaps in Zapier.
- Remove `webhook_secret`, `_generate_webhook_secret`, and the old `legal_document_signed_webhook` view. Follow
  `safe-django-migrations.md`: in one PR drop all references + SeparateDatabaseAndState `RemoveField` (state only),
  then in a follow-up PR drop the column.
- Remove the `LEGAL_DOCUMENTS_OWNED_PANDADOC` feature flag.

## Why this is worth doing

- **Ownership & observability.** Zapier failures are currently invisible to us — Zaps silently stop on errors,
  customers get nothing, and our only signal is a customer complaint. Owning the code means PandaDoc errors land in
  Sentry and Slack, PandaDoc retries land in our logs, and we have a "Resend envelope" admin action.
- **Context for humans.** Slack + Vitally means whoever covers the org sees a submission in real time with TAM and
  ARR already attached, so they can reach out without hunting through CRMs.
- **Simpler auth story.** PandaDoc already gives us a stable `document_id`; using it as the join key removes the
  need for `webhook_secret`, `legal_document_id` in the PostHog event, and the constant-time secret compare. We
  authenticate PandaDoc's callbacks with PandaDoc's own HMAC signature — the standard way.
- **Fewer surprises.** One Python codepath replaces two Zaps, a PostHog event trigger, and a shared secret echoed
  through three systems. Easier to review, easier to debug, easier to roll back.

## Critical files to create / modify

- `products/legal_documents/backend/integrations/pandadoc.py` — new client
- `products/legal_documents/backend/integrations/vitally.py` — new client
- `products/legal_documents/backend/integrations/slack.py` — new helper (or reuse existing)
- `products/legal_documents/backend/tasks/notify_legal_document.py` — Celery task for Slack + Vitally
- `products/legal_documents/backend/presentation/webhook.py` — replace the secret webhook with HMAC-verified PandaDoc webhook
- `products/legal_documents/backend/presentation/views.py` — replace `_fire_zapier_event` with direct PandaDoc create + Celery enqueue
- `products/legal_documents/backend/models.py` — add `pandadoc_document_id`; eventually drop `webhook_secret`
- New migration: `add_pandadoc_document_id`
- Later migration (phase 3): `drop_webhook_secret`
- `posthog/settings/web.py` — new env-backed settings
- `posthog/urls.py` — change the webhook URL from `<id>/signed` to `pandadoc_webhook`
- `frontend/src/lib/constants.tsx` — add `LEGAL_DOCUMENTS_OWNED_PANDADOC` feature flag constant

## Verification

1. Unit tests:
   - `PandaDocClient`: mock `requests.post` and assert the right URL, auth header, and body shape for each document
     type / DPA mode.
   - Vitally client: mocked happy path, 404 path, timeout path — all return sensible structures.
   - Slack helper: builds the right Block Kit payload with and without Vitally data.
   - Webhook: valid HMAC signature on a `document_state_changed` payload → row moves to `signed` and gets a URL;
     wrong signature → 404; unknown `pandadoc_document_id` → 404; wrong event type → 204 no-op.
2. Integration test with `responses` mocking PandaDoc + Vitally: full create flow on a test org updates the row,
   enqueues the Celery task, and the task posts a well-formed Slack payload.
3. Manual smoke in staging with real PandaDoc sandbox credentials before flipping the flag on prod.
4. Keep the existing `test_legal_document_signed_webhook` tests passing throughout phase 1–2 (same endpoint still
   accepts the old-style payload for Zapier-originated rows).

## Known unknowns to resolve before we start

- Confirm with RevOps how Vitally accounts are keyed (domain? Stripe customer ID? something else) — dictates the
  Vitally lookup parameter.
- Get PandaDoc templates built for all three variants (BAA, DPA pretty, DPA lawyer) with the token names above. The
  `fairytale` and `tswift` modes remain preview-only — no template needed.
- Decide: mirror the signed PDF to S3 for stable URLs, or always re-fetch from PandaDoc on click? Start with
  re-fetch (simpler, no storage to manage) and revisit if customers complain about 404s.
