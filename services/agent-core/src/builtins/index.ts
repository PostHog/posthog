import { z } from 'zod'

/**
 * Registry of built-in tool ids that agent-stack manifests are allowed to reference.
 *
 * Authoritative source for both the runner (which executes them) and the future
 * validator (which rejects unknown ids at deploy time). Keep entries minimal — only
 * the contract; the runner registers the actual implementations against these ids.
 */

export interface BuiltinSpec {
    /** Public id used in agent-stack manifests. Stable. */
    id: string
    /** Short human description for UIs and the validator's reports. */
    description: string
    /** JSON schema for the tool's arguments, expressed as a zod schema. */
    args: z.ZodTypeAny
    /** Allowed action names for this tool, when the manifest uses fine-grained allow-listing. */
    actions?: readonly string[]
}

const BUILTIN_SPECS: readonly BuiltinSpec[] = [
    {
        id: 'posthog.events.capture',
        description: 'Capture an event into PostHog product analytics.',
        args: z.object({
            event: z.string().min(1),
            distinctId: z.string().min(1),
            properties: z.record(z.string(), z.unknown()).optional(),
        }),
    },
    {
        id: 'posthog.feature_flags.evaluate',
        description: 'Evaluate a PostHog feature flag for a given distinct id.',
        args: z.object({
            flag: z.string().min(1),
            distinctId: z.string().min(1),
            groups: z.record(z.string(), z.string()).optional(),
        }),
    },
    {
        id: 'http.fetch',
        description: 'Make an outbound HTTP request from the agent runtime.',
        args: z.object({
            url: z.string().url(),
            method: z.enum(['GET', 'POST', 'PUT', 'PATCH', 'DELETE']).default('GET'),
            headers: z.record(z.string(), z.string()).optional(),
            body: z.string().optional(),
            timeoutMs: z.number().int().min(1).max(60_000).default(10_000),
        }),
    },
] as const

const BUILTIN_INDEX: ReadonlyMap<string, BuiltinSpec> = new Map(BUILTIN_SPECS.map((spec) => [spec.id, spec]))

export function listBuiltins(): readonly BuiltinSpec[] {
    return BUILTIN_SPECS
}

export function getBuiltin(id: string): BuiltinSpec | null {
    return BUILTIN_INDEX.get(id) ?? null
}

export function isBuiltinId(id: string): boolean {
    return BUILTIN_INDEX.has(id)
}
