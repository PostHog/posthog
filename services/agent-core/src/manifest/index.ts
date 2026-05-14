import { z } from 'zod'

import { isBuiltinId } from '../builtins'

/**
 * Minimal manifest shape used by the v1 runner. The full validator (services/agent-validator,
 * deferred) will parse bundle contents, walk the YAML tree, and produce a richer parsed_manifest.
 * In v1, the Django side stores top_level_config from the CLI's parse step and the runner reads
 * it directly. Both code paths share this schema so they agree on what's valid.
 */

const ToolReferenceSchema = z.object({
    id: z.string().min(1),
    /** Optional action allow-list when the manifest opts into fine-grained scoping. */
    actions: z.array(z.string()).optional(),
})

const TriggerSchema = z.discriminatedUnion('kind', [
    z.object({ kind: z.literal('http'), path: z.string().startsWith('/') }),
    z.object({ kind: z.literal('cron'), schedule: z.string().min(1) }),
    z.object({ kind: z.literal('webhook'), provider: z.string().min(1) }),
])

export const ManifestSchema = z.object({
    name: z.string().min(1),
    description: z.string().optional(),
    entrypoint: z.string().min(1),
    tools: z.array(ToolReferenceSchema).default([]),
    triggers: z.array(TriggerSchema).default([]),
})

export type Manifest = z.infer<typeof ManifestSchema>
export type ToolReference = z.infer<typeof ToolReferenceSchema>
export type Trigger = z.infer<typeof TriggerSchema>

export interface ManifestValidationError {
    path: string
    message: string
}

export interface ManifestValidationResult {
    manifest: Manifest | null
    errors: ManifestValidationError[]
}

/**
 * Parse + validate raw manifest data. Returns a structured result rather than throwing
 * so callers (Django start_deploy, the future validator, the CLI) can surface all errors
 * at once.
 */
export function parseManifest(raw: unknown): ManifestValidationResult {
    const parsed = ManifestSchema.safeParse(raw)
    if (!parsed.success) {
        return {
            manifest: null,
            errors: parsed.error.issues.map((issue) => ({
                path: issue.path.join('.') || '<root>',
                message: issue.message,
            })),
        }
    }

    const errors: ManifestValidationError[] = []
    parsed.data.tools.forEach((tool, index) => {
        if (!isBuiltinId(tool.id)) {
            errors.push({
                path: `tools.${index}.id`,
                message: `unknown built-in tool id: ${tool.id}`,
            })
        }
    })

    return {
        manifest: errors.length === 0 ? parsed.data : null,
        errors,
    }
}
