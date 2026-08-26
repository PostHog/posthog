import type { ToolBase, ZodObjectAny } from '@/tools/types'

/**
 * Merge codegen and hand-written tool factories.
 * Hand-written entries win on key collision so overrides (e.g. update-feature-flag
 * group-targeting) actually reach production catalogs, CLI, and tests.
 *
 * Always use this helper instead of inlining spreads so merge sites cannot
 * drift (tool-catalog, cli/tools, getToolsFromContext, and tests).
 */
export function mergeToolFactories(
    generated: Record<string, () => ToolBase<ZodObjectAny>>,
    handwritten: Record<string, () => ToolBase<ZodObjectAny>>
): Record<string, () => ToolBase<ZodObjectAny>> {
    // Hand-written keys are laid down first so the catalog keeps the order it had
    // before any override existed. Key order is observable: it decides the order
    // tools are listed in and which ones the compact domain index is built from.
    const merged: Record<string, () => ToolBase<ZodObjectAny>> = { ...handwritten, ...generated }
    for (const [name, factory] of Object.entries(handwritten)) {
        merged[name] = factory
    }
    return merged
}
