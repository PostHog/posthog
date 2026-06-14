/**
 * Typed configuration loader for the ingress.
 *
 * Extends `PlatformConfigSchema` with the trigger / routing knobs. Read once
 * at boot in `index.ts`; everything else inside the service receives the
 * typed `Config` via constructor / function arg.
 */

import { z } from 'zod'

import { extendEnvKeyMap, loadConfigFromEnv, PLATFORM_ENV_KEY_MAP, PlatformConfigSchema } from '@posthog/agent-shared'

export const AgentIngressConfigSchema = PlatformConfigSchema.extend({
    port: z.coerce.number().int().positive().default(8080).describe('HTTP listen port.'),
    routingMode: z
        .enum(['path', 'domain'])
        .default('path')
        .describe(
            '`path` (`/agents/<slug>/...`) for local dev; `domain` (`<slug>.agents.<suffix>`) for prod with wildcard DNS.'
        ),
    domainSuffix: z
        .string()
        .optional()
        .describe('Required in domain mode — e.g. `.agents.posthog.com`. Stripped from Host to extract the slug.'),
    pathPrefix: z
        .string()
        .default('/agents')
        .describe('URL prefix in path mode (default `/agents`). Slug comes immediately after.'),
    internalSigningKey: z
        .string()
        .optional()
        .describe(
            "HMAC signing key shared with Django and the janitor (must match Django's `AGENT_INTERNAL_SIGNING_KEY`). Verifies x-agent-preview-token on non-live invokes (aud = agent-ingress.preview). Unset → preview gate bypassed (dev / harness only)."
        ),
    publicUrl: z
        .string()
        .optional()
        .describe(
            'Public URL this ingress is reachable at from the outside world (e.g. `https://agents.us.posthog.com`, or a `https://<id>.trycloudflare.com` in local dev via `bin/agent-tunnel`). Optional and debug-only: when set it is logged on boot so you can spot mismatches with what Slack / webhooks are pointed at. Unset is normal — domain-mode routes by host, and Django builds the `slack_events_url` it returns from its own `AGENT_INGRESS_*` settings, not from this value.'
        ),
})

export type AgentIngressConfig = z.infer<typeof AgentIngressConfigSchema>

const ENV_KEY_MAP = extendEnvKeyMap<AgentIngressConfig>(PLATFORM_ENV_KEY_MAP, {
    PORT: 'port',
    ROUTING_MODE: 'routingMode',
    DOMAIN_SUFFIX: 'domainSuffix',
    PATH_PREFIX: 'pathPrefix',
    AGENT_INTERNAL_SIGNING_KEY: 'internalSigningKey',
    AGENT_INGRESS_PUBLIC_URL: 'publicUrl',
})

export function loadAgentIngressConfig(env: NodeJS.ProcessEnv = process.env): AgentIngressConfig {
    return loadConfigFromEnv(AgentIngressConfigSchema, ENV_KEY_MAP, env)
}
