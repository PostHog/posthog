import type { z } from 'zod'

import { wrapError } from '@/lib/errors'
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
 * clean list. Preserves the stored ARRAY order: the backend (`apply_path_cleaning` →
 * `Team.path_cleaning_filter_models`) applies rules in array order and ignores the `order`
 * field for sequencing, so re-sorting by `order` here could silently resequence untouched
 * rules on save. The `order` field is carried through only as display metadata.
 */
export function normalizePathCleaningFilters(raw: unknown): StoredPathCleaningRule[] {
    if (!Array.isArray(raw)) {
        return []
    }
    return (
        raw
            .map((entry, index) => {
                const rule = (entry ?? {}) as Record<string, unknown>
                const alias = typeof rule.alias === 'string' ? rule.alias : ''
                const regex = typeof rule.regex === 'string' ? rule.regex : ''
                const order = typeof rule.order === 'number' ? rule.order : index
                return { alias, regex, order }
            })
            // An empty `alias` is a valid rule (it deletes the matched text), so only drop
            // entries with no `regex` to match on — keeping an existing empty-alias rule
            // instead of silently deleting it on the next confirmed edit.
            .filter((rule) => rule.regex !== '')
    )
}

/** Reassign contiguous `order` values 0..n-1 so the caller never has to manage them. */
export function renumber(rules: PathCleaningRule[]): StoredPathCleaningRule[] {
    return rules.map((rule, index) => ({ ...rule, order: index }))
}

/**
 * Apply the ordered operations to a copy of the current rules, returning the new list and a
 * human-readable change log. Throws with an actionable message on any invalid operation
 * (unknown or ambiguous target alias, non-permutation reorder) so nothing is half-applied.
 */
export function applyOperations(
    current: PathCleaningRule[],
    operations: Operation[]
): { rules: PathCleaningRule[]; changes: string[] } {
    const rules: PathCleaningRule[] = current.map((rule) => ({ ...rule }))
    const changes: string[] = []

    // Aliases are NOT guaranteed unique (two regexes can map to the same alias), so an
    // alias-targeted op is only safe when exactly one rule carries it — otherwise we'd
    // silently edit an arbitrary one. Reject the ambiguous case rather than guess.
    const resolveSingle = (alias: string, verb: string): number => {
        const matches = rules.reduce<number[]>((acc, rule, i) => {
            if (rule.alias === alias) {
                acc.push(i)
            }
            return acc
        }, [])
        if (matches.length === 0) {
            throw new Error(
                `Cannot ${verb}: no rule with alias "${alias}". Existing aliases: ${rules.map((rule) => rule.alias).join(', ')}`
            )
        }
        if (matches.length > 1) {
            throw new Error(
                `Cannot ${verb}: alias "${alias}" matches ${matches.length} rules, so targeting it is ambiguous. Make the aliases distinct first, or edit the full list via project-settings-update.`
            )
        }
        return matches[0]!
    }

    for (const op of operations) {
        switch (op.action) {
            case 'append': {
                rules.push({ alias: op.alias, regex: op.regex })
                changes.push(`Appended "${op.alias}" (${op.regex}) — runs last`)
                break
            }
            case 'insert': {
                const index = Math.min(op.index, rules.length)
                rules.splice(index, 0, { alias: op.alias, regex: op.regex })
                changes.push(`Inserted "${op.alias}" (${op.regex}) at position ${index}`)
                break
            }
            case 'replace': {
                const index = resolveSingle(op.target_alias, 'replace')
                const previous = rules[index]!
                const next = { alias: op.alias ?? previous.alias, regex: op.regex ?? previous.regex }
                rules[index] = next
                changes.push(`Replaced "${op.target_alias}" → alias "${next.alias}", regex ${next.regex}`)
                break
            }
            case 'remove': {
                const index = resolveSingle(op.target_alias, 'remove')
                rules.splice(index, 1)
                changes.push(`Removed "${op.target_alias}"`)
                break
            }
            case 'reorder': {
                // Group rules by alias so duplicate aliases are handled without loss: the
                // permutation check is a true multiset comparison, and the rebuild consumes
                // same-alias rules in their original relative order.
                const groups = new Map<string, PathCleaningRule[]>()
                for (const rule of rules) {
                    const list = groups.get(rule.alias)
                    if (list) {
                        list.push(rule)
                    } else {
                        groups.set(rule.alias, [rule])
                    }
                }
                const requestedCounts = new Map<string, number>()
                for (const alias of op.ordered_aliases) {
                    requestedCounts.set(alias, (requestedCounts.get(alias) ?? 0) + 1)
                }
                const isPermutation =
                    op.ordered_aliases.length === rules.length &&
                    [...requestedCounts].every(([alias, count]) => (groups.get(alias)?.length ?? 0) === count)
                if (!isPermutation) {
                    throw new Error(
                        `Cannot reorder: ordered_aliases must be exactly the current aliases, once each (including duplicates). Current: ${rules
                            .map((rule) => rule.alias)
                            .join(', ')}`
                    )
                }
                const queues = new Map([...groups].map(([alias, list]) => [alias, [...list]]))
                const reordered = op.ordered_aliases.map((alias) => queues.get(alias)!.shift()!)
                rules.splice(0, rules.length, ...reordered)
                changes.push(`Reordered to: ${op.ordered_aliases.join(' → ')}`)
                break
            }
        }
    }

    return { rules, changes }
}

type PreviewQuery = { query: string; values: Record<string, string | string[]> }

/** Mirrors `apply_path_cleaning`: one `replaceRegexpAll` per rule, in array order, each feeding the next. */
function cleanedPathExpression(rules: PathCleaningRule[], prefix: string, values: PreviewQuery['values']): string {
    return rules.reduce((expression, rule, index) => {
        values[`${prefix}_regex_${index}`] = rule.regex
        values[`${prefix}_alias_${index}`] = rule.alias
        return `replaceRegexpAll(${expression}, {${prefix}_regex_${index}}, {${prefix}_alias_${index}})`
    }, 'path')
}

function buildSamplePreviewQuery(
    before: PathCleaningRule[],
    after: PathCleaningRule[],
    samplePaths: string[]
): PreviewQuery {
    const values: PreviewQuery['values'] = { sample_paths: samplePaths }
    const beforeExpression = cleanedPathExpression(before, 'before', values)
    const afterExpression = cleanedPathExpression(after, 'after', values)
    return {
        query: `SELECT arrayMap(path -> ${beforeExpression}, {sample_paths}), arrayMap(path -> ${afterExpression}, {sample_paths})`,
        values,
    }
}

async function buildSamplePreview(
    context: Context,
    projectId: string,
    before: PathCleaningRule[],
    after: PathCleaningRule[],
    samplePaths: string[]
): Promise<SamplePreview[]> {
    const result = await context.api.insights({ projectId }).query({
        query: { kind: 'HogQLQuery', ...buildSamplePreviewQuery(before, after, samplePaths) },
    })
    if (!result.success) {
        throw wrapError(
            `The sample_paths preview failed to run (${result.error.message}). Check that every regex is valid re2, or retry without sample_paths.`,
            result.error
        )
    }
    const [cleanedBefore, cleanedAfter] = ((result.data.results as unknown[][] | undefined)?.[0] ?? []) as [
        string[]?,
        string[]?,
    ]
    if (cleanedBefore?.length !== samplePaths.length || cleanedAfter?.length !== samplePaths.length) {
        throw new Error('The sample_paths preview returned an unexpected result. Retry without sample_paths.')
    }
    return samplePaths.map((path, index) => ({ path, before: cleanedBefore[index]!, after: cleanedAfter[index]! }))
}

export const updatePathCleaningHandler: ToolBase<typeof schema, Result>['handler'] = async (
    context: Context,
    params: Params
) => {
    const projectId = await context.stateManager.getProjectId()

    const projectResult = await context.api.projects().get({ projectId })
    if (!projectResult.success) {
        throw wrapError(
            `Failed to read current path cleaning rules: ${projectResult.error.message}`,
            projectResult.error
        )
    }

    const currentStored = normalizePathCleaningFilters(
        (projectResult.data as { path_cleaning_filters?: unknown }).path_cleaning_filters
    )
    const currentRules: PathCleaningRule[] = currentStored.map(({ alias, regex }) => ({ alias, regex }))

    const { rules, changes } = applyOperations(currentRules, params.operations)
    const resultingRules = renumber(rules)

    const samplePreview = params.sample_paths?.length
        ? await buildSamplePreview(context, projectId, currentRules, rules, params.sample_paths)
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
        throw wrapError(`Failed to save path cleaning rules: ${updateResult.error.message}`, updateResult.error)
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
