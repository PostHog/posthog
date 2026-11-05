# PostHog SDKs for transactional email

Read the section for the backend's language. Each SDK sends both forms with one `send` call: a code send names a `template_key` with a subject and an HTML or text body, and a template send names a `template_id` with its data. A send names one of the two, never both. Each section gives the minimum version that sends content from code. Install the latest release, and never one below that version.

Every SDK takes the same optional fields as the HTTP API: `from`, `reply_to` and `capture_engagement` on a code send. Every SDK also takes an idempotency key, retries network errors, rate limits and a `503` with that key, and doesn't retry a `not_found` from a status read.

## Node.js

- **Package:** `posthog-node`, version `<release>` or later.
- **Client:** `new PostHog(projectToken, { host, secretKey })`. Behind a reverse proxy or on a self-hosted instance, set `appHost` to the PostHog app URL. The client polls feature flag definitions with the secret key, so a client that only sends email sets `enableLocalEvaluation: false`, unless the key also has the feature flag read scope.
- **Code send:** `posthog.emails.send({ templateKey, to, subject, html, text, distinctId, idempotencyKey })`, with `from`, `replyTo` and `captureEngagement` optional.
- **Template send:** `posthog.emails.send({ to, templateId, templateData, distinctId, idempotencyKey })`.
- **Result:** `{ data, error }`. It doesn't throw on an API error. `data.id` is the message ID, and `error.code` is the error code.
- **Status:** `posthog.emails.get(messageId)` returns `{ data, error }`.

## Python

- **Package:** `posthog` (`posthog[async]` for `AsyncPosthog`), version `<release>` or later.
- **Client:** `Posthog(project_token, host=..., secret_key=...)`. Behind a reverse proxy or on a self-hosted instance, set `app_host`. The client loads flag definitions only when it evaluates a flag.
- **Code send:** `posthog.emails.send(template_key=..., to=..., subject=..., html=..., text=..., distinct_id=..., idempotency_key=...)`, with `from_`, `reply_to` and `capture_engagement` optional.
- **Template send:** `posthog.emails.send(to=..., template_id=..., template_data=..., distinct_id=..., idempotency_key=...)`.
- **Result:** a `SendEmailResult` with `id`. It raises `EmailError`, imported from `posthog.emails`, with `code`.
- **Status:** `posthog.emails.get(message_id)` returns an `EmailStatus`.

## Go

- **Package:** `github.com/posthog/posthog-go`, version `<release>` or later.
- **Client:** `posthog.NewWithConfig(projectToken, posthog.Config{Endpoint: ..., SecretKey: ...})`. Behind a reverse proxy or on a self-hosted instance, set `AppHost`. With `SecretKey` set, the client polls flag definitions with it, so give the key the feature flag read scope too, or it logs a failed poll each time.
- **Code send:** `client.Emails().Send(ctx, posthog.CodeEmail{To, TemplateKey, Subject, HTML, Text, DistinctID, IdempotencyKey})`, with `From`, `ReplyTo` and `CaptureEngagement` (`posthog.Ptr(false)`) optional.
- **Template send:** `client.Emails().Send(ctx, posthog.TemplateEmail{To, TemplateID, TemplateData, DistinctID, IdempotencyKey})`.
- **Result:** a `*posthog.SendEmailResult` with `ID`, and an error that is a `*posthog.EmailError` with `Code`.
- **Status:** `client.Emails().Get(ctx, messageID)` returns a `*posthog.EmailStatus`.

## Ruby

- **Package:** the `posthog-ruby` gem, version `<release>` or later.
- **Client:** `PostHog::Client.new({ api_key: ..., host: ..., secret_key: ... })`. Behind a reverse proxy or on a self-hosted instance, set `app_host`. With `secret_key` set, the client loads flag definitions with it when it starts, so give the key the feature flag read scope too.
- **Code send:** `client.emails.send(to:, template_key:, subject:, html:, text:, distinct_id:, idempotency_key:)`, with `from:`, `reply_to:` and `capture_engagement:` optional.
- **Template send:** `client.emails.send(to:, template_id:, template_data:, distinct_id:, idempotency_key:)`.
- **Result:** a `SendResult` with `id`. It raises `PostHog::EmailError`, with `code`.
- **Status:** `client.emails.get(message_id)` returns a `Status`.

## PHP

- **Package:** `posthog/posthog-php` with Composer, version `<release>` or later.
- **Client:** `PostHog::init($projectToken, ['host' => ...], secretKey: ...)`. Behind a reverse proxy or on a self-hosted instance, set the `app_host` option. With `secretKey` set, the client loads flag definitions with it when it starts: give the key the feature flag read scope too, or build the client with `loadFeatureFlags: false` in a process that only sends email.
- **Code send:** `PostHog::emails()->send(['to' => ..., 'template_key' => ..., 'subject' => ..., 'html' => ..., 'text' => ..., 'distinct_id' => ..., 'idempotency_key' => ...])`, with `'from'`, `'reply_to'` and `'capture_engagement'` optional.
- **Template send:** `PostHog::emails()->send(['to' => ..., 'template_id' => ..., 'template_data' => [...], 'distinct_id' => ..., 'idempotency_key' => ...])`.
- **Result:** a `SendEmailResult`, with `getId()`. It throws `PostHog\EmailError`, with `getErrorCode()`.
- **Status:** `PostHog::emails()->get($messageId)`.

## .NET

- **Package:** `PostHog` on NuGet, version `<release>` or later.
- **Client:** set `SecretKey` on `PostHogOptions`. With ASP.NET's `builder.AddPostHog()`, set `PostHog:SecretKey` in configuration and inject `IPostHogEmails`. Otherwise use `posthog.Emails` on a `PostHogClient`. Behind a reverse proxy or on a self-hosted instance, set `AppHost`. The client loads flag definitions only when it evaluates a flag.
- **Code send:** `await emails.SendAsync(new SendCodeEmailOptions { To, TemplateKey, Subject, Html, Text, DistinctId, IdempotencyKey })`, with `From`, `ReplyTo` and `CaptureEngagement` optional.
- **Template send:** `await emails.SendAsync(new SendTemplateEmailOptions { To, TemplateId, TemplateData, DistinctId, IdempotencyKey })`.
- **Result:** a `SendEmailResult` with `Id`. It throws `EmailException`, with `Code`.
- **Status:** `await emails.GetAsync(messageId)` returns an `EmailStatus`.

## Rust

- **Package:** the `posthog-rs` crate, version `<release>` or later.
- **Client:** `ClientOptionsBuilder::default().api_key(...).host(...).secret_key(...)`. Behind a reverse proxy or on a self-hosted instance, set `app_host`. The client loads flag definitions only with `enable_local_evaluation` on.
- **Code send:** `posthog.emails().send(CodeEmail::new(to, template_key, subject).html(...).text(...).distinct_id(...).idempotency_key(...))`, with `.from(...)`, `.reply_to(...)` and `.capture_engagement(false)` optional.
- **Template send:** `posthog.emails().send(TemplateEmail::new(to, template_id).template_data(...).distinct_id(...).idempotency_key(...))`.
- **Result:** a `SendEmailResult` with `id`, or a `posthog_rs::EmailError`, with `code()`.
- **Status:** `posthog.emails().get(message_id)` returns an `EmailStatus`.

## Elixir

- **Package:** `{:posthog, "~> <release>"}` in `mix.exs`.
- **Client:** set `secret_key` in the `:posthog` config, next to `api_host` and `api_key`. Behind a reverse proxy or on a self-hosted instance, set `app_host`. With `secret_key` set, the SDK loads flag definitions with it when it starts: give the key the feature flag read scope too, or set `enable_local_evaluation: false`.
- **Code send:** `PostHog.Emails.send(to: ..., template_key: ..., subject: ..., html: ..., text: ..., distinct_id: ..., idempotency_key: ...)`, with `from:`, `reply_to:` and `capture_engagement:` optional.
- **Template send:** `PostHog.Emails.send(to: ..., template_id: ..., template_data: %{...}, distinct_id: ..., idempotency_key: ...)`.
- **Result:** `{:ok, result}` with `result.id`, or `{:error, %PostHog.Emails.Error{}}`, with `code`.
- **Status:** `PostHog.Emails.get(message_id)` returns `{:ok, %PostHog.Emails.Status{}}` or `{:error, error}`.
