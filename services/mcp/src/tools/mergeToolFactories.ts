import type { ToolBase, ZodObjectAny } from '@/tools/types'

/**
 * Merge codegen and hand-written tool factories.
 * Hand-written entries win on key collision so overrides (e.g. update-feature-flag
 * group-targeting) actually reach production catalogs, CLI, and tests.
 *
 * Always use this helper instead of inlining spreads so the three call sites
 * (tool-catalog, cli/tools, getToolsFromContext) cannot drift.
 */
export function mergeToolFactories(
    generated: Record<string, () => ToolBase<ZodObjectAny>>,
    handwritten: Record<string, () => ToolBase<ZodObjectAny>>
): Record<string, () => ToolBase<ZodObjectAny>> {
    return { ...generated, ...handwritten }
}
