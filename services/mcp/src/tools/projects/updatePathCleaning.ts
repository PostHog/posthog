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

function assertValidRegex(regex: string): void {
    // The backend compiles these as re2; JS RegExp is only a best-effort typo check to fail
    // fast on obviously-broken patterns (e.g. unbalanced parens). Strip a leading re2 inline
    // flag group like `(?i)` first — it's valid re2 (and documented for path cleaning) but
    // throws in JS. Patterns valid in re2 but not JS still save fine; the backend is the
    // authority and rejects genuinely invalid ones on write.
    const withoutLeadingInlineFlags = regex.replace(/^\(\?[imsUx]+\)/, '')
    try {
        new RegExp(withoutLeadingInlineFlags)
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
                const index = resolveSingle(op.target_alias, 'replace')
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

/**
 * Compile a re2 pattern into a JS RegExp for the approximate preview. Translates a leading
 * re2 inline-flag group (e.g. `(?i)`) into JS flags so patterns accepted by the tool don't
 * silently drop out of the preview. Returns null for patterns JS can't represent.
 */
function compileForPreview(regex: string): RegExp | null {
    const match = regex.match(/^\(\?([imsUx]+)\)/)
    const inlineFlags = match ? match[1]! : ''
    const pattern = match ? regex.slice(match[0].length) : regex
    // Map the re2 flags JS supports; ignore U/x (no JS equivalent, and rare in path cleaning).
    let flags = 'g'
    if (inlineFlags.includes('i')) {
        flags += 'i'
    }
    if (inlineFlags.includes('m')) {
        flags += 'm'
    }
    if (inlineFlags.includes('s')) {
        flags += 's'
    }
    try {
        return new RegExp(pattern, flags)
    } catch {
        // A rule using re2-only syntax may not compile under JS RegExp — skip it in the
        // approximate preview rather than failing the whole call.
        return null
    }
}

/** Chain a path through every rule in order, mirroring ClickHouse `replaceRegexpAll` per rule. */
function applyChain(path: string, rules: PathCleaningRule[]): string {
    let out = path
    for (const rule of rules) {
        const re = compileForPreview(rule.regex)
        if (re === null) {
            continue
        }
        // `alias` is a literal; escape `$` so JS's replace() doesn't treat it as a group ref.
        out = out.replace(re, rule.alias.replace(/\$/g, '$$$$'))
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
