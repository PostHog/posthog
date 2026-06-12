/**
 * Typed configuration loader for the ingress.
 *
 * Extends `PlatformConfigSchema` with the trigger / routing knobs. Read once
 * at boot in `index.ts`; everything else inside the service receives the
 * typed `Config` via constructor / function arg.
 *
 * Plan + rationale: `docs/agent-platform/plans/typed-config-loader.md`.
 */

import { z } from 'zod'

import { extendEnvKeyMap, loadConfigFromEnv, PLATFORM_ENV_KEY_MAP, PlatformConfigSchema } from '@posthog/agent-shared'

export const AgentIngressConfigSchema = PlatformConfigSchema.extend({
    port: z.coerce.number().int().positive().default(8080).describe('HTTP listen port.'),
    teamId: z.coerce
        .number()
        .int()
        .positive()
        .default(1)
        .describe('Team that owns all routed agents in this deployment. v1 is single-tenant.'),
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
            "HMAC signing key shared with Django and the janitor (must match Django's `AGENT_INTERNAL_SIGNING_KEY`). Verifies x-agent-preview-token on non-live invokes (aud = agent-ingress.preview). Unset → preview gate bypassed (dev / harness only). See docs/agent-platform/plans/draft-preview-auth.md."
        ),
    aiGatewayUrl: z
        .string()
        .optional()
        .describe(
            'ai-gateway base URL the inference proxy forwards to (trailing /v1 stripped). Set together with POSTHOG_AI_GATEWAY_KEY to mount /inference/v1/* — the session-scoped model proxy for tier-2 coding sandboxes. Unset → proxy route absent.'
        ),
    posthogAiGatewayKey: z
        .string()
        .optional()
        .describe(
            'Real gateway credential the inference proxy attaches upstream. Lives ONLY here — tier-2 sandboxes hold a session-bound capability token instead (see agent-sandbox-tiers.md §8).'
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
    TEAM_ID: 'teamId',
    ROUTING_MODE: 'routingMode',
    DOMAIN_SUFFIX: 'domainSuffix',
    PATH_PREFIX: 'pathPrefix',
    AGENT_INTERNAL_SIGNING_KEY: 'internalSigningKey',
    AGENT_INGRESS_PUBLIC_URL: 'publicUrl',
    POSTHOG_AI_GATEWAY_URL: 'aiGatewayUrl',
    POSTHOG_AI_GATEWAY_KEY: 'posthogAiGatewayKey',
})

export function loadAgentIngressConfig(env: NodeJS.ProcessEnv = process.env): AgentIngressConfig {
    return loadConfigFromEnv(AgentIngressConfigSchema, ENV_KEY_MAP, env)
}
