import type { z } from 'zod'

import { GENERATED_TOOLS } from '@/tools/generated/signals'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

/**
 * Deprecation aliases for the `signals-scout-*` → `scout-*` rename. Each old name
 * forwards arguments to the current handler and annotates the response so agents
 * (including persisted custom scout skills authored against the old names) discover
 * the new name without the call failing. Remove this whole file (and the matching
 * `tool-definitions.json` entries + index.ts registration) once callers have
 * migrated off the `signals-scout-*` prefix.
 */
const RENAMES: Record<string, string> = {
    'signals-scout-config-create': 'scout-config-create',
    'signals-scout-config-delete': 'scout-config-delete',
    'signals-scout-config-list': 'scout-config-list',
    'signals-scout-config-sync': 'scout-config-sync',
    'signals-scout-config-update': 'scout-config-update',
    'signals-scout-edit-report': 'scout-edit-report',
    'signals-scout-emit-report': 'scout-emit-report',
    'signals-scout-emit-signal': 'scout-emit-signal',
    'signals-scout-members-list': 'scout-members-list',
    'signals-scout-project-profile-get': 'scout-project-profile-get',
    'signals-scout-run-now': 'scout-run-now',
    'signals-scout-runs-emission-reports': 'scout-runs-emission-reports',
    'signals-scout-runs-emissions-list': 'scout-runs-emissions-list',
    'signals-scout-runs-list': 'scout-runs-list',
    'signals-scout-runs-recent-emissions': 'scout-runs-recent-emissions',
    'signals-scout-runs-retrieve': 'scout-runs-retrieve',
    'signals-scout-scratchpad-forget': 'scout-scratchpad-forget',
    'signals-scout-scratchpad-remember': 'scout-scratchpad-remember',
    'signals-scout-scratchpad-search': 'scout-scratchpad-search',
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

/** Old `signals-scout-*` name → alias factory, spread into TOOL_MAP. */
export const SIGNALS_SCOUT_DEPRECATED_ALIASES: Record<string, () => ToolBase<ZodObjectAny>> = Object.fromEntries(
    Object.entries(RENAMES).map(([oldName, newName]) => [oldName, makeAlias(oldName, newName)])
)
