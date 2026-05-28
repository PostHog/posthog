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
    slackSigningSecret: z
        .string()
        .optional()
        .describe('Verifies inbound Slack webhook signatures. Required for the Slack trigger.'),
    previewSecret: z
        .string()
        .optional()
        .describe(
            'HMAC secret shared with Django. Verifies x-agent-preview-token on non-live invokes. Unset → gate bypassed (dev / harness). See docs/agent-platform/plans/draft-preview-auth.md.'
        ),
})

export type AgentIngressConfig = z.infer<typeof AgentIngressConfigSchema>

const ENV_KEY_MAP = extendEnvKeyMap<AgentIngressConfig>(PLATFORM_ENV_KEY_MAP, {
    PORT: 'port',
    TEAM_ID: 'teamId',
    ROUTING_MODE: 'routingMode',
    DOMAIN_SUFFIX: 'domainSuffix',
    PATH_PREFIX: 'pathPrefix',
    SLACK_SIGNING_SECRET: 'slackSigningSecret',
    AGENT_PREVIEW_SECRET: 'previewSecret',
})

export function loadAgentIngressConfig(env: NodeJS.ProcessEnv = process.env): AgentIngressConfig {
    const cfg = loadConfigFromEnv(AgentIngressConfigSchema, ENV_KEY_MAP, env)
    // Legacy fallback: pre-AGENT_PREVIEW_SECRET deployments shared INTERNAL_SECRET
    // between Django and the node services. Honor it here so existing prod
    // configs keep working without an env split. Plan: drop the fallback once
    // every env explicitly sets AGENT_PREVIEW_SECRET.
    if (!cfg.previewSecret && env.INTERNAL_SECRET) {
        cfg.previewSecret = env.INTERNAL_SECRET
    }
    return cfg
}
