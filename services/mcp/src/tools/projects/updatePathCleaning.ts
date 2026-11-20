import { RE2JS } from 're2js'
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

// RE2 copies a `{n}` operand n times, so a short pattern can compile slowly enough to block the event loop.
const MAX_PROGRAM_SIZE = 1000
// replaceAll searches again after every match, so preview cost can grow with path length squared.
const PREVIEW_WORK_BUDGET = 20_000_000

const COUNTED_REPEAT = /\{(\d+)(?:,(\d*))?\}/y
const GROUP_PREFIX = /\(\?(?:P?<[^>]*>|[a-zA-Z-]*:?)/y

function estimateProgramSize(regex: string): number {
    const frames = [{ size: 0, last: 0, capturing: false }]
    let i = 0
    while (i < regex.length) {
        const char = regex[i]!
        COUNTED_REPEAT.lastIndex = i
        const repeat = COUNTED_REPEAT.exec(regex)
        if (repeat) {
            const [text, min, max] = repeat
            const count = max === undefined ? Number(min) : max === '' ? Number(min) + 1 : Number(max)
            const frame = frames[frames.length - 1]!
            frame.size += frame.last * (count - 1)
            frame.last *= count
            i += text.length
            continue
        }
        if (char === '(') {
            GROUP_PREFIX.lastIndex = i
            const groupPrefix = GROUP_PREFIX.exec(regex)?.[0] ?? '('
            frames.push({ size: 0, last: 0, capturing: groupPrefix === '(' || groupPrefix.endsWith('>') })
            i += groupPrefix.length
            continue
        }
        if ('*+?|'.includes(char)) {
            frames[frames.length - 1]!.size++
            i++
            continue
        }
        let atom = 1
        let next = i + 1
        if (char === ')' && frames.length > 1) {
            const group = frames.pop()!
            atom = group.size + (group.capturing ? 2 : 0)
        } else if (char === '\\' && regex[i + 1] === 'Q') {
            const end = regex.indexOf('\\E', i)
            next = end === -1 ? regex.length : end + 2
            atom = next - i
        } else if (char === '\\') {
            next = i + 2
            if ('xpP'.includes(regex[i + 1] ?? '') && regex[next] === '{') {
                next = regex.indexOf('}', next) + 1 || regex.length
            }
        } else if (char === '[') {
            next = i + 1
            if (regex[next] === '^') {
                next++
            }
            if (regex[next] === ']') {
                next++
            }
            while (next < regex.length && regex[next] !== ']') {
                next += regex[next] === '\\' ? 2 : 1
            }
            next++
        }
        const frame = frames[frames.length - 1]!
        frame.size += atom
        frame.last = atom
        i = next
    }
    return frames.reduce((sum, frame) => sum + frame.size, 0)
}

function compilePathCleaningRegex(regex: string): RE2JS {
    if (estimateProgramSize(regex) > MAX_PROGRAM_SIZE) {
        throw new Error('pattern is too complex')
    }
    const compiled = RE2JS.compile(regex)
    if (compiled.programSize() > MAX_PROGRAM_SIZE) {
        throw new Error('pattern is too complex')
    }
    return compiled
}

function assertValidRegex(regex: string): void {
    try {
        compilePathCleaningRegex(regex)
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
 * Expand an alias against one regex match, so the preview substitutes capture groups the same way
 * the real query does. The alias is re2 replacement syntax: `\0` is the whole match, `\1` to `\9`
 * are capture groups, `\\` is a literal backslash, and everything else is literal.
 *
 * Expanding against the match here, rather than translating to a `$1`-style replacement string,
 * keeps three re2 rules JavaScript would otherwise break: `$` stays literal, `\10` is group 1
 * followed by `0` rather than group 10, and an unfilled group substitutes as empty.
 */
export function expandAlias(alias: string, groups: (string | undefined)[]): string {
    let out = ''
    for (let i = 0; i < alias.length; i++) {
        const char = alias[i]
        if (char !== '\\') {
            out += char
            continue
        }
        const next = alias[i + 1]
        if (next === '\\') {
            out += '\\'
            i++
        } else if (next !== undefined && next >= '0' && next <= '9') {
            out += groups[Number(next)] ?? ''
            i++
        } else {
            out += '\\'
        }
    }
    return out
}

type CompiledRule = { alias: string; re: RE2JS }

function compileForPreview(rules: PathCleaningRule[]): CompiledRule[] {
    return rules.flatMap((rule) => {
        try {
            return [{ alias: rule.alias, re: compilePathCleaningRegex(rule.regex) }]
        } catch {
            // Stored rules skipped this tool's validation, so a rule RE2 refuses is left out of the preview.
            return []
        }
    })
}

/** Chain a path through every rule in order, mirroring ClickHouse `replaceRegexpAll` per rule. */
function applyChain(path: string, rules: CompiledRule[], spend: (work: number) => void): string {
    let out = path
    for (const { alias, re } of rules) {
        const input = out
        const cost = re.programSize() * (re.groupCount() + 1)
        spend(input.length * cost)
        out = re.matcher(input).replaceAll((match: string, ...rest: unknown[]): string => {
            // Replacer arguments run (match, p1…pN, offset, whole string, named groups?). A group
            // the pattern didn't fill arrives as undefined, so the first number is the offset and
            // marks where the capture values stop.
            const offsetIndex = rest.findIndex((arg) => typeof arg === 'number')
            const offset = rest[offsetIndex] as number
            const captures = rest.slice(0, offsetIndex) as (string | undefined)[]
            const replacement = expandAlias(alias, [match, ...captures])
            spend((input.length - offset - match.length) * cost + replacement.length)
            return replacement
        })
    }
    return out
}

function buildSamplePreview(
    before: PathCleaningRule[],
    after: PathCleaningRule[],
    samplePaths: string[]
): SamplePreview[] {
    const compiledBefore = compileForPreview(before)
    const compiledAfter = compileForPreview(after)
    let budget = PREVIEW_WORK_BUDGET
    const spend = (work: number): void => {
        budget -= work
        if (budget < 0) {
            throw new Error(
                'The sample preview is too expensive for these rules and paths. Retry with fewer or shorter sample_paths.'
            )
        }
    }
    return samplePaths.map((path) => ({
        path,
        before: applyChain(path, compiledBefore, spend),
        after: applyChain(path, compiledAfter, spend),
    }))
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
