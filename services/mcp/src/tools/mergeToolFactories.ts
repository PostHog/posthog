import type { ToolBase, ZodObjectAny } from '@/tools/types'

/**
 * Merge codegen and hand-written tool factories. Hand-written entries win on key
 * collision. Use this helper at every merge site rather than inlining a spread, so
 * the sites cannot drift apart.
 *
 * The arguments are named rather than positional because both maps have the same
 * type. A swapped positional call would invert precedence with no type error, and
 * only the one colliding tool would behave differently.
 */
export function mergeToolFactories({
    generated,
    handwritten,
}: {
    generated: Record<string, () => ToolBase<ZodObjectAny>>
    handwritten: Record<string, () => ToolBase<ZodObjectAny>>
}): Record<string, () => ToolBase<ZodObjectAny>> {
    // Key order is observable: it sets the listing order and which tools the compact
    // domain index is built from. Laying hand-written keys down first keeps the order
    // the catalog had before any override existed.
    const merged: Record<string, () => ToolBase<ZodObjectAny>> = { ...handwritten, ...generated }
    for (const [name, factory] of Object.entries(handwritten)) {
        merged[name] = factory
    }
    return merged
}
