import type { z } from 'zod'

import { PathCleaningRulesUpdateSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = PathCleaningRulesUpdateSchema

type Params = z.infer<typeof schema>
type Operation = Params['operations'][number]

/** A path cleaning rule as the LLM works with it — order is managed by this tool, not the caller. */
export type PathCleaningRule = { alias: string; regex: string }
/** A rule as stored on the project (`Team.path_cleaning_filters`), with an explicit order. */
export type StoredPathCleaningRule = PathCleaningRule & { order: number }

type SamplePreview = { path: string; before: string; after: string }

type Result = {
    applied: boolean
    message: string
    changes: string[]
    resulting_rules: StoredPathCleaningRule[]
    sample_preview?: SamplePreview[]
    settings_url: string
}

/**
 * Coerce the raw `path_cleaning_filters` value (typed `unknown` in the API schema) into a
 * clean, order-sorted list. Tolerates missing/duplicate `order` by falling back to array index.
 */
export function normalizePathCleaningFilters(raw: unknown): StoredPathCleaningRule[] {
    if (!Array.isArray(raw)) {
        return []
    }
    return raw
        .map((entry, index) => {
            const rule = (entry ?? {}) as Record<string, unknown>
            const alias = typeof rule.alias === 'string' ? rule.alias : ''
            const regex = typeof rule.regex === 'string' ? rule.regex : ''
            const order = typeof rule.order === 'number' ? rule.order : index
            return { alias, regex, order, _index: index }
        })
        .filter((rule) => rule.alias !== '' && rule.regex !== '')
        .sort((a, b) => a.order - b.order || a._index - b._index)
        .map(({ alias, regex, order }) => ({ alias, regex, order }))
}

/** Reassign contiguous `order` values 0..n-1 so the caller never has to manage them. */
export function renumber(rules: PathCleaningRule[]): StoredPathCleaningRule[] {
    return rules.map((rule, index) => ({ alias: rule.alias, regex: rule.regex, order: index }))
}

function assertValidRegex(regex: string): void {
    try {
        new RegExp(regex)
    } catch (error) {
        throw new Error(`Invalid regex "${regex}": ${(error as Error).message}`)
    }
}

/**
 * Apply the ordered operations to a copy of the current rules, returning the new list and a
 * human-readable change log. Throws with an actionable message on any invalid operation
 * (unknown target alias, bad regex, non-permutation reorder) so nothing is half-applied.
 */
export function applyOperations(
    current: PathCleaningRule[],
    operations: Operation[]
): { rules: PathCleaningRule[]; changes: string[] } {
    const rules: PathCleaningRule[] = current.map((rule) => ({ ...rule }))
    const changes: string[] = []

    const findByAlias = (alias: string): number => rules.findIndex((rule) => rule.alias === alias)

    for (const op of operations) {
        switch (op.action) {
            case 'append': {
                assertValidRegex(op.regex)
                rules.push({ alias: op.alias, regex: op.regex })
                changes.push(`Appended "${op.alias}" (${op.regex}) — runs last`)
                break
            }
            case 'insert': {
                assertValidRegex(op.regex)
                const index = Math.min(op.index, rules.length)
                rules.splice(index, 0, { alias: op.alias, regex: op.regex })
                changes.push(`Inserted "${op.alias}" (${op.regex}) at position ${index}`)
                break
            }
            case 'replace': {
                const index = findByAlias(op.target_alias)
                if (index === -1) {
                    throw new Error(
                        `Cannot replace: no rule with alias "${op.target_alias}". Existing aliases: ${rules
                            .map((rule) => rule.alias)
                            .join(', ')}`
                    )
                }
                if (op.regex !== undefined) {
                    assertValidRegex(op.regex)
                }
                const previous = rules[index]!
                const next = { alias: op.alias ?? previous.alias, regex: op.regex ?? previous.regex }
                rules[index] = next
                changes.push(`Replaced "${op.target_alias}" → alias "${next.alias}", regex ${next.regex}`)
                break
            }
            case 'remove': {
                const index = findByAlias(op.target_alias)
                if (index === -1) {
                    throw new Error(
                        `Cannot remove: no rule with alias "${op.target_alias}". Existing aliases: ${rules
                            .map((rule) => rule.alias)
                            .join(', ')}`
                    )
                }
                rules.splice(index, 1)
                changes.push(`Removed "${op.target_alias}"`)
                break
            }
            case 'reorder': {
                const currentAliases = rules.map((rule) => rule.alias).sort()
                const requestedAliases = [...op.ordered_aliases].sort()
                const isPermutation =
                    currentAliases.length === requestedAliases.length &&
                    currentAliases.every((alias, i) => alias === requestedAliases[i])
                if (!isPermutation) {
                    throw new Error(
                        `Cannot reorder: ordered_aliases must be exactly the current aliases, once each. Current: ${rules
                            .map((rule) => rule.alias)
                            .join(', ')}`
                    )
                }
                const byAlias = new Map(rules.map((rule) => [rule.alias, rule]))
                const reordered = op.ordered_aliases.map((alias) => byAlias.get(alias)!)
                rules.splice(0, rules.length, ...reordered)
                changes.push(`Reordered to: ${op.ordered_aliases.join(' → ')}`)
                break
            }
        }
    }

    return { rules, changes }
}

/** Chain a path through every rule in order, mirroring ClickHouse `replaceRegexpAll` per rule. */
function applyChain(path: string, rules: PathCleaningRule[]): string {
    let out = path
    for (const rule of rules) {
        try {
            const re = new RegExp(rule.regex, 'g')
            // `alias` is a literal; escape `$` so JS's replace() doesn't treat it as a group ref.
            out = out.replace(re, rule.alias.replace(/\$/g, '$$$$'))
        } catch {
            // A rule using re2-only syntax may not compile under JS RegExp — skip it in the
            // approximate preview rather than failing the whole call.
        }
    }
    return out
}

function buildSamplePreview(
    before: PathCleaningRule[],
    after: PathCleaningRule[],
    samplePaths: string[]
): SamplePreview[] {
    return samplePaths.map((path) => ({
        path,
        before: applyChain(path, before),
        after: applyChain(path, after),
    }))
}

export const updatePathCleaningHandler: ToolBase<typeof schema, Result>['handler'] = async (
    context: Context,
    params: Params
) => {
    const projectId = await context.stateManager.getProjectId()

    const projectResult = await context.api.projects().get({ projectId })
    if (!projectResult.success) {
        throw new Error(`Failed to read current path cleaning rules: ${projectResult.error.message}`)
    }

    const currentStored = normalizePathCleaningFilters(
        (projectResult.data as { path_cleaning_filters?: unknown }).path_cleaning_filters
    )
    const currentRules: PathCleaningRule[] = currentStored.map(({ alias, regex }) => ({ alias, regex }))

    const { rules, changes } = applyOperations(currentRules, params.operations)
    const resultingRules = renumber(rules)

    const samplePreview = params.sample_paths?.length
        ? buildSamplePreview(currentRules, rules, params.sample_paths)
        : undefined

    const settingsUrl = `${context.api.getProjectBaseUrl(projectId)}/settings/project#path-cleaning`

    if (!params.confirm) {
        return {
            applied: false,
            message: `Preview only — nothing saved. ${changes.length} change(s) would apply, leaving ${resultingRules.length} rule(s). Re-run with confirm:true to save.`,
            changes,
            resulting_rules: resultingRules,
            sample_preview: samplePreview,
            settings_url: settingsUrl,
        }
    }

    const updateResult = await context.api.projects().updatePathCleaningFilters({
        projectId,
        filters: resultingRules,
    })
    if (!updateResult.success) {
        throw new Error(`Failed to save path cleaning rules: ${updateResult.error.message}`)
    }

    const saved = normalizePathCleaningFilters(
        (updateResult.data as { path_cleaning_filters?: unknown }).path_cleaning_filters
    )

    return {
        applied: true,
        message: `Saved ${saved.length} path cleaning rule(s). These apply globally wherever path cleaning is enabled and can change historical numbers.`,
        changes,
        resulting_rules: saved,
        sample_preview: samplePreview,
        settings_url: settingsUrl,
    }
}

const tool = (): ToolBase<typeof schema, Result> => ({
    name: 'path-cleaning-rules-update',
    schema,
    handler: updatePathCleaningHandler,
})

export default tool
