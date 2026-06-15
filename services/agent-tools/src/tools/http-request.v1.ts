/**
 * Generic HTTP client tool — POST/PUT/PATCH/DELETE/GET against arbitrary URLs.
 *
 * Use this for any HTTP API where the platform doesn't ship a typed native
 * tool: Slack chat.postMessage, GitHub REST, Linear, internal services, etc.
 * The author pastes their bearer/PAT into `spec.secrets[]` (via the
 * concierge's `set_secret` flow) and references it by name as `${TOKEN}` in
 * `url` / `headers` / `body`; the substitution happens server-side so the
 * plaintext value never appears in the model's tool-call history.
 *
 * Auth / SSRF stance — identical to `@posthog/web-fetch`:
 *   - SSRF protection is enforced at the egress hop by smokescreen (see
 *     `charts/shared/agent-platform/common.yaml`). The runner doesn't try to
 *     vet hostnames; smokescreen denies RFC1918 / loopback / cloud IMDS and
 *     re-resolves DNS per-IP at connect time.
 *   - The tool itself has no concept of integrations. If the agent author
 *     wants the platform-managed OAuth path (shared bot identity, central
 *     token rotation), use the typed `@posthog/slack-*` tools instead.
 *
 * Why this isn't just web-fetch with a method param: response bodies for
 * mutation calls (Slack, GitHub) carry useful payloads the model needs to
 * inspect (`{ok: true, ts: '17...'}`), and request bodies are first-class
 * inputs. The schema is a superset of web-fetch but the surface is wide
 * enough that keeping them separate makes the description clearer to the
 * model — `web-fetch` is for "read a page," `http-request` is for "call an
 * API."
 */

import { defineNativeTool, SECRET_WILDCARD, type ToolContext, Type } from '@posthog/agent-shared'

const SECRET_REF = /\$\{([A-Z][A-Z0-9_]*)\}/g

/**
 * Replace `${SECRET_NAME}` placeholders with resolved values from `ctx.secret`.
 * Missing names throw so the agent gets a clear `secret_not_resolved: NAME`
 * error rather than silently sending a literal `${NAME}` to the upstream
 * (which would 401 with a confusing error from the remote).
 */
function substituteSecrets(input: string, ctx: ToolContext): string {
    return input.replace(SECRET_REF, (_match, name: string) => {
        const value = ctx.secret(name)
        if (value === undefined) {
            throw new Error(`secret_not_resolved: ${name}`)
        }
        return value
    })
}

function substituteHeaders(headers: Record<string, string> | undefined, ctx: ToolContext): Record<string, string> {
    if (!headers) {
        return {}
    }
    const out: Record<string, string> = {}
    for (const [k, v] of Object.entries(headers)) {
        out[k] = substituteSecrets(v, ctx)
    }
    return out
}

/**
 * Serialize `body` for the wire. Object → JSON + `Content-Type: application/json`
 * unless the caller already set a content-type header. String passes through
 * verbatim. Undefined → no body sent.
 *
 * Secret substitution happens AFTER serialization so a token can live inside
 * a JSON value (e.g. `{"token": "${SLACK_BOT_TOKEN}"}`) without the author
 * having to think about escaping.
 */
function serializeBody(
    body: string | Record<string, unknown> | undefined,
    headers: Record<string, string>,
    ctx: ToolContext
): { body: string | undefined; headers: Record<string, string> } {
    if (body === undefined) {
        return { body: undefined, headers }
    }
    if (typeof body === 'string') {
        return { body: substituteSecrets(body, ctx), headers }
    }
    const hasContentType = Object.keys(headers).some((k) => k.toLowerCase() === 'content-type')
    const finalHeaders = hasContentType ? headers : { ...headers, 'Content-Type': 'application/json; charset=utf-8' }
    return { body: substituteSecrets(JSON.stringify(body), ctx), headers: finalHeaders }
}

const DEFAULT_MAX_RESPONSE_BYTES = 1_000_000
const ABSOLUTE_MAX_RESPONSE_BYTES = 5_000_000
const DEFAULT_TIMEOUT_MS = 15_000
const ABSOLUTE_MAX_TIMEOUT_MS = 60_000

export const httpRequestV1 = defineNativeTool({
    id: '@posthog/http-request',
    description: [
        'Make an arbitrary HTTP request (GET/POST/PUT/PATCH/DELETE) against a URL.',
        'Use this for any service where the platform does not ship a typed tool —',
        "Slack's Web API, GitHub REST, Linear, internal services, etc. Reference",
        'secrets declared in `spec.secrets` as `${NAME}` inside url, headers, or',
        'body; the runner substitutes the plaintext value before the request goes',
        "out, so the token never appears in the model's tool-call history.",
        'For Slack specifically: POST to `https://slack.com/api/<method>` with',
        '`Authorization: Bearer ${SLACK_BOT_TOKEN}` and a JSON body.',
    ].join(' '),
    args: Type.Object({
        url: Type.String({
            format: 'uri',
            description: 'Target URL. May contain `${NAME}` placeholders that resolve from spec.secrets.',
        }),
        method: Type.Optional(
            Type.Union(
                [
                    Type.Literal('GET'),
                    Type.Literal('POST'),
                    Type.Literal('PUT'),
                    Type.Literal('PATCH'),
                    Type.Literal('DELETE'),
                ],
                { default: 'GET', description: 'HTTP method. Default GET.' }
            )
        ),
        headers: Type.Optional(
            Type.Record(Type.String(), Type.String(), {
                description:
                    'Request headers. Values may contain `${NAME}` placeholders. Authorization headers are the typical use case.',
            })
        ),
        body: Type.Optional(
            Type.Union([Type.String(), Type.Record(Type.String(), Type.Unknown())], {
                description:
                    'Request body. Strings are sent verbatim; objects are JSON-encoded and Content-Type defaults to application/json. `${NAME}` placeholders work inside either form.',
            })
        ),
        timeout_ms: Type.Optional(
            Type.Integer({
                minimum: 1,
                maximum: ABSOLUTE_MAX_TIMEOUT_MS,
                description: `Per-request timeout in ms (default ${DEFAULT_TIMEOUT_MS}, max ${ABSOLUTE_MAX_TIMEOUT_MS}).`,
            })
        ),
        max_response_bytes: Type.Optional(
            Type.Integer({
                minimum: 1,
                maximum: ABSOLUTE_MAX_RESPONSE_BYTES,
                description: `Cap on response body bytes returned to the model (default ${DEFAULT_MAX_RESPONSE_BYTES}, max ${ABSOLUTE_MAX_RESPONSE_BYTES}). Bodies larger than this are truncated.`,
            })
        ),
    }),
    returns: Type.Object({
        status: Type.Number(),
        body: Type.String(),
        content_type: Type.String(),
        /** Selected response headers — model rarely needs more than a handful. */
        headers: Type.Record(Type.String(), Type.String()),
        url: Type.String(),
        truncated: Type.Boolean({ description: 'True if the response body was clipped to max_response_bytes.' }),
    }),
    // Resolves `${NAME}` placeholders by author-supplied name, so it must reach
    // any secret the spec declares — the `*` wildcard scopes it to `spec.secrets`
    // (still narrower than the raw decrypted env).
    requires: { integrations: [], scopes: ['web:fetch'], secrets: [SECRET_WILDCARD] },
    cost_hint: 'medium',
    async run(args, ctx) {
        const url = substituteSecrets(args.url, ctx)
        const method = args.method ?? 'GET'
        const headersIn = substituteHeaders(args.headers, ctx)
        const { body, headers: finalHeaders } = serializeBody(args.body, headersIn, ctx)
        const maxBytes = args.max_response_bytes ?? DEFAULT_MAX_RESPONSE_BYTES
        const timeoutMs = args.timeout_ms ?? DEFAULT_TIMEOUT_MS

        // Sanity check the URL parses; the runtime fetch would throw anyway,
        // but a clear error here helps the model retry.
        try {
            new URL(url)
        } catch {
            throw new Error(`invalid_url: ${url}`)
        }

        const controller = new AbortController()
        const abortTimer = setTimeout(() => controller.abort(), timeoutMs)

        let res: Response
        try {
            res = await ctx.http.fetch(url, {
                method,
                headers: finalHeaders,
                body,
                signal: controller.signal,
            })
        } catch (err) {
            const e = err as Error & { name?: string }
            if (e.name === 'AbortError') {
                throw new Error(`http_request_timeout: ${timeoutMs}ms`)
            }
            throw new Error(`http_request_failed: ${e.message ?? 'unknown'}`)
        } finally {
            clearTimeout(abortTimer)
        }

        const text = await res.text()
        const truncated = text.length > maxBytes
        const bodyOut = truncated ? text.slice(0, maxBytes) : text

        // Surface a small fixed set of useful response headers; sending every
        // header back inflates the context for no model-side payoff.
        const HEADER_ALLOWLIST = new Set(['content-type', 'content-length', 'location', 'retry-after', 'date'])
        const headersOut: Record<string, string> = {}
        for (const [k, v] of res.headers.entries()) {
            if (HEADER_ALLOWLIST.has(k.toLowerCase())) {
                headersOut[k] = v
            }
        }

        ctx.log('info', 'http.request.completed', {
            method,
            url,
            status: res.status,
            response_bytes: text.length,
            truncated,
        })

        return {
            status: res.status,
            body: bodyOut,
            content_type: res.headers.get('content-type') ?? '',
            headers: headersOut,
            url,
            truncated,
        }
    },
})
