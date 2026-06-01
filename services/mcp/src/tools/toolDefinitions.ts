import z from 'zod'

import type { EvaluatedFlags } from '@/lib/posthog/flags'

import generatedToolDefinitionsJson from '../../schema/generated-tool-definitions.json'
import toolDefinitionsJson from '../../schema/tool-definitions.json'

export const ToolDefinitionSchema = z
    .object({
        description: z.string(),
        category: z.string(),
        feature: z.string(),
        summary: z.string(),
        title: z.string(),
        required_scopes: z.array(z.string()),
        requires_ai_consent: z.boolean().optional(),
        /** PostHog feature flag key that gates this tool. */
        feature_flag: z.string().optional(),
        /** How the flag gates the tool: 'enable' (default) or 'disable'. */
        feature_flag_behavior: z.enum(['enable', 'disable']).optional(),
        /** Variant of `feature_flag` to match exactly. Requires `feature_flag` to be set. */
        feature_flag_variant: z.string().optional(),
        /** One-line selection hint surfaced in the system prompt's query tool catalog. */
        system_prompt_hint: z.string().optional(),
        /**
         * When true, the tool is exposed even when the client passes a `features`
         * or `tools` allowlist that wouldn't otherwise match. Reserved for
         * cross-cutting utility tools (e.g. feedback) that should remain
         * discoverable to every client without forcing them to opt in.
         * Other filters (readOnly, AI consent, feature flags, scopes) still apply.
         */
        always_available: z.boolean().optional(),
        annotations: z.object({
            destructiveHint: z.boolean(),
            idempotentHint: z.boolean(),
            openWorldHint: z.boolean(),
            readOnlyHint: z.boolean(),
        }),
    })
    .refine((data) => !(data.feature_flag_variant && !data.feature_flag), {
        message: '`feature_flag_variant` requires `feature_flag` to be set',
        path: ['feature_flag_variant'],
    })

export type ToolDefinition = z.infer<typeof ToolDefinitionSchema>

export type ToolDefinitions = Record<string, ToolDefinition>

const toolDefinitionsSchema = z.record(z.string(), ToolDefinitionSchema)

let _toolDefinitions: ToolDefinitions | undefined = undefined
let _generatedToolDefinitions: ToolDefinitions | undefined = undefined

function getGeneratedToolDefinitions(): ToolDefinitions {
    if (!_generatedToolDefinitions) {
        _generatedToolDefinitions = toolDefinitionsSchema.parse(generatedToolDefinitionsJson)
    }
    return _generatedToolDefinitions
}

export function getToolDefinitions(): ToolDefinitions {
    const generated = getGeneratedToolDefinitions()
    if (!_toolDefinitions) {
        _toolDefinitions = toolDefinitionsSchema.parse(toolDefinitionsJson)
    }
    return { ..._toolDefinitions, ...generated }
}

export function getToolDefinition(toolName: string): ToolDefinition {
    const toolDefinitions = getToolDefinitions()

    const definition = toolDefinitions[toolName]

    if (!definition) {
        throw new Error(`Tool definition not found for: ${toolName}`)
    }

    return definition
}

export interface ToolFilterOptions {
    features?: string[] | undefined
    tools?: string[] | undefined
    excludeTools?: string[] | undefined
    readOnly?: boolean | undefined
    aiConsentGiven?: boolean | undefined
    /** Used to gate tools that declare `feature_flag` in their YAML config. */
    featureFlags?: EvaluatedFlags | undefined
    /**
     * Project IDs the token is restricted to (`scoped_teams` on the API key).
     * When set, the backend 403s any org-level endpoint, so we drop tools that
     * need `organization:*` scopes — they'd fail anyway.
     */
    scopedTeams?: number[] | undefined
}

/**
 * Collect all distinct feature flag keys referenced by tool definitions.
 * Used at init time to batch-evaluate flags before filtering tools.
 */
export function getRequiredFeatureFlags(): string[] {
    const toolDefinitions = getToolDefinitions()
    const flags = new Set<string>()
    for (const definition of Object.values(toolDefinitions)) {
        if (definition.feature_flag) {
            flags.add(definition.feature_flag)
        }
    }
    return [...flags]
}

function normalizeFeatureName(name: string): string {
    return name.replace(/-/g, '_')
}

/**
 * Predicate: does a tool's `feature_flag` configuration permit it under the
 * given evaluation map? An undefined map is treated as "no flags evaluated".
 *
 *   no `feature_flag`         → always passes
 *   `feature_flag_variant` set → flag value must equal the variant string
 *   `feature_flag_behavior: 'enable'` (default) → flag must be `=== true`
 *   `feature_flag_behavior: 'disable'` → flag must NOT be `=== true`
 */
export function toolPassesFlagGate(definition: ToolDefinition, featureFlags: EvaluatedFlags = {}): boolean {
    if (!definition.feature_flag) {
        // Belt-and-braces: the schema `.refine` rejects this at parse time, but
        // `z.infer` strips refinements so TS lets callers hand-roll a bad
        // ToolDefinition. Treat the misconfig as "always hidden" rather than
        // silently ungated.
        return definition.feature_flag_variant === undefined
    }
    const flagValue = featureFlags[definition.feature_flag]
    if (definition.feature_flag_variant !== undefined) {
        return flagValue === definition.feature_flag_variant
    }
    const isOn = flagValue === true
    return (definition.feature_flag_behavior ?? 'enable') === 'enable' ? isOn : !isOn
}

export function getToolsForFeatures(options?: ToolFilterOptions): string[] {
    const { features, tools, readOnly, aiConsentGiven, featureFlags, scopedTeams } = options || {}
    const toolDefinitions = getToolDefinitions()

    let entries = Object.entries(toolDefinitions)

    // Filter by features and/or tools allowlist (OR union).
    // When both are provided, a tool is included if it matches a feature category OR is in the tools list.
    // Normalize hyphens to underscores so that both "error-tracking" and "error_tracking" match.
    // Tools marked `always_available` bypass this allowlist so utility tools
    // (e.g. feedback) stay discoverable for every client.
    const hasFeatures = features && features.length > 0
    const hasTools = tools && tools.length > 0
    if (hasFeatures || hasTools) {
        const normalizedFeatures = hasFeatures ? new Set(features.map(normalizeFeatureName)) : null
        const allowedTools = hasTools ? new Set(tools) : null

        entries = entries.filter(([toolName, definition]) => {
            if (definition.always_available) {
                return true
            }
            const matchesFeature = normalizedFeatures
                ? definition.feature && normalizedFeatures.has(normalizeFeatureName(definition.feature))
                : false
            const matchesTool = allowedTools ? allowedTools.has(toolName) : false
            return matchesFeature || matchesTool
        })
    }

    // In read-only mode, only expose tools annotated as read-only
    if (readOnly) {
        entries = entries.filter(([_, definition]) => definition.annotations.readOnlyHint === true)
    }

    // When AI consent is not given or not yet fetched, exclude tools that require it
    if (!aiConsentGiven) {
        entries = entries.filter(([_, definition]) => !definition.requires_ai_consent)
    }

    // Filter by feature flags — see {@link toolPassesFlagGate} for the predicate.
    entries = entries.filter(([_, definition]) => toolPassesFlagGate(definition, featureFlags))

    // Hide tools that need org-level access when the session's token is
    // project-scoped - the backend would 403 them
    if (scopedTeams && scopedTeams.length > 0) {
        entries = entries.filter(
            ([_, definition]) => !(definition.required_scopes ?? []).some((scope) => scope.startsWith('organization'))
        )
    }

    return entries.map(([toolName, _]) => toolName)
}
