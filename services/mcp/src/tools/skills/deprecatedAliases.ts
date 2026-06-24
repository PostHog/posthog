import type { z } from 'zod'

import { GENERATED_TOOLS } from '@/tools/generated/skills'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

/**
 * Deprecation aliases for the `llma-skill-*` → `skill-*` rename. Each old name
 * forwards arguments to the current handler and annotates the response so agents
 * discover the new name without the call failing. Remove this whole file (and the
 * matching `tool-definitions.json` entries + index.ts registrations) once callers
 * have migrated off the `llma-skill-*` prefix.
 */
const RENAMES: Record<string, string> = {
    'llma-skill-archive': 'skill-archive',
    'llma-skill-create': 'skill-create',
    'llma-skill-duplicate': 'skill-duplicate',
    'llma-skill-file-create': 'skill-file-create',
    'llma-skill-file-delete': 'skill-file-delete',
    'llma-skill-file-get': 'skill-file-get',
    'llma-skill-file-rename': 'skill-file-rename',
    'llma-skill-get': 'skill-get',
    'llma-skill-list': 'skill-list',
    'llma-skill-update': 'skill-update',
}

function makeAlias(oldName: string, newName: string): () => ToolBase<ZodObjectAny> {
    return (): ToolBase<ZodObjectAny> => {
        const inner = GENERATED_TOOLS[newName]!()
        return {
            ...inner,
            name: oldName,
            handler: async (context: Context, params: z.infer<ZodObjectAny>) => {
                const result = await inner.handler(context, params)
                return {
                    ...(result as object),
                    _deprecation_notice: `${oldName} has been renamed to ${newName}. Call ${newName} directly next time — this alias will be removed.`,
                }
            },
        }
    }
}

/** Old `llma-skill-*` name → alias factory, spread into TOOL_MAP. */
export const SKILL_DEPRECATED_ALIASES: Record<string, () => ToolBase<ZodObjectAny>> = Object.fromEntries(
    Object.entries(RENAMES).map(([oldName, newName]) => [oldName, makeAlias(oldName, newName)])
)
