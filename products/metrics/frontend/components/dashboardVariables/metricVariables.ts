import { objectsEqual } from 'lib/utils/objects'

import type { MetricsDashboardVariable, MetricsDashboardVariableSelection } from '~/queries/schema/schema-general'

import type { _MetricVariableSelectionApi } from 'products/metrics/frontend/generated/api.schemas'

/** The select value that stands for All. A query can return any text, so it is a character that options do not hold. */
export const ALL_OPTION = '\u0000all'
export const VARIABLE_NAME = /^[A-Za-z_][A-Za-z0-9_]*$/
/** The API accepts selected values up to this length. */
export const MAX_VALUE_LENGTH = 1024
const REFERENCE =
    /\$\{([A-Za-z0-9_]+)(?::[A-Za-z0-9_]+)?\}|\[\[([A-Za-z0-9_]+)(?::[A-Za-z0-9_]+)?\]\]|\$([A-Za-z0-9_]+)/g

export function referencedNames(text: string | null | undefined): string[] {
    const names = new Set<string>()
    for (const match of (text ?? '').matchAll(REFERENCE)) {
        names.add(match[1] ?? match[2] ?? match[3])
    }
    return [...names]
}

function previousNonSpace(text: string, index: number): number {
    let before = index - 1
    while (before >= 0 && /\s/.test(text[before])) {
        before--
    }
    return before
}

function functionNameBefore(text: string, index: number): string {
    const end = previousNonSpace(text, index) + 1
    let start = end
    while (start > 0 && /[A-Za-z0-9_:]/.test(text[start - 1])) {
        start--
    }
    return text.slice(start, end).toLowerCase()
}

/** Follows the backend: a `#` comment holds no references, a regex-escaped `$` in a regex is a literal, and
 * `replacements: false` leaves out the replacement argument of label_replace, where `$name` can be a regex group. */
export function promqlReferencedNames(
    query: string | null | undefined,
    { replacements = true }: { replacements?: boolean } = {}
): string[] {
    const text = query ?? ''
    // The quote of the string that holds each position, or '#' inside a comment.
    const contexts: (string | null)[] = []
    // The positions inside a regex string, such as `=~"..."` or the regex argument of label_replace.
    const inRegex: boolean[] = []
    const inReplacement: boolean[] = []
    // The open brackets, each with the function name before a parenthesis and the argument index.
    const groups: { bracket: string; name: string; argument: number }[] = []
    let quote: string | null = null
    let regex = false
    let replacement = false
    for (let index = 0; index < text.length; index++) {
        const char = text[index]
        contexts[index] = quote
        inRegex[index] = regex
        inReplacement[index] = replacement
        if (quote === '#') {
            quote = char === '\n' || char === '\r' ? null : quote
        } else if (quote) {
            if (char === '\\' && quote !== '`') {
                contexts[index + 1] = quote
                inRegex[index + 1] = regex
                inReplacement[index + 1] = replacement
                index++
            } else if (char === quote) {
                quote = null
            }
        } else if (char === '(' || char === '{') {
            const name = char === '(' ? functionNameBefore(text, index) : ''
            groups.push({ bracket: char, name, argument: 0 })
        } else if (char === ')' || char === '}') {
            if (groups.at(-1)?.bracket === (char === ')' ? '(' : '{')) {
                groups.pop()
            }
        } else if (char === ',') {
            const group = groups.at(-1)
            if (group) {
                group.argument++
            }
        } else if (char === '#' || char === '"' || char === "'" || char === '`') {
            quote = char
            contexts[index] = char === '#' ? '#' : null
            const call = groups.at(-1)
            const labelReplace = call?.bracket === '(' && call.name === 'label_replace'
            const before = previousNonSpace(text, index)
            const afterMatcher =
                before > 0 && text[before] === '~' && (text[before - 1] === '=' || text[before - 1] === '!')
            regex = char !== '#' && (afterMatcher || (labelReplace && call.argument === 4))
            replacement = char !== '#' && labelReplace && call.argument === 2
        }
    }
    const names = new Set<string>()
    for (const match of text.matchAll(REFERENCE)) {
        const context = contexts[match.index] ?? null
        if (context === '#' || (!replacements && context && inReplacement[match.index])) {
            continue
        }
        if (context && inRegex[match.index]) {
            let backslashes = 0
            while (text[match.index - backslashes - 1] === '\\') {
                backslashes++
            }
            if ((context === '`' ? backslashes : Math.floor(backslashes / 2)) % 2 === 1) {
                continue
            }
        }
        names.add(match[1] ?? match[2] ?? match[3])
    }
    return [...names]
}

const SQL_REFERENCE = /\$\{([A-Za-z0-9_]+)(?::[A-Za-z0-9_]+)?\}|\$([A-Za-z0-9_]+)/y

/** Follows the backend: comments and quoted identifiers hold no references, and `[[x]]` is a nested array. */
export function sqlReferencedNames(sql: string | null | undefined): string[] {
    const text = sql ?? ''
    const names = new Set<string>()
    let index = 0
    while (index < text.length) {
        const char = text[index]
        const lineComment =
            text.startsWith('--', index) ||
            text.startsWith('//', index) ||
            (char === '#' && !/[0-9]/.test(text[index + 1] ?? ''))
        if (lineComment) {
            const end = text.slice(index).search(/[\r\n]/)
            index = end < 0 ? text.length : index + end
        } else if (text.startsWith('/*', index)) {
            const end = text.indexOf('*/', index + 2)
            index = end < 0 ? text.length : end + 2
        } else if (char === "'" || char === '"' || char === '`') {
            let end = index + 1
            while (end < text.length && text[end] !== char) {
                end += text[end] === '\\' ? 2 : 1
            }
            if (char === "'") {
                referencedNames(text.slice(index + 1, end)).forEach((name) => names.add(name))
            }
            index = end + 1
        } else {
            SQL_REFERENCE.lastIndex = index
            const match = SQL_REFERENCE.exec(text)
            const previous = text[index - 1] ?? ''
            if (match && !/[A-Za-z0-9_.$]/.test(previous)) {
                names.add(match[1] ?? match[2])
                index = SQL_REFERENCE.lastIndex
            } else {
                index += 1
            }
        }
    }
    return [...names].filter((name) => !name.startsWith('__') && !/^[0-9]+$/.test(name))
}

/** Includes the variable itself when its query refers to it, so that `orderVariables` reports the loop. */
export function variableParents(variable: MetricsDashboardVariable, variables: MetricsDashboardVariable[]): string[] {
    if (variable.source !== 'promql' && variable.source !== 'sql') {
        return []
    }
    const names = new Set(variables.map((other) => other.name))
    if (variable.source === 'sql') {
        return sqlReferencedNames(variable.query).filter((name) => names.has(name))
    }
    // The query of a variable gets no value for the variable itself, so in a replacement `$name` stays a regex group.
    const own = promqlReferencedNames(variable.query, { replacements: false }).includes(variable.name)
    return promqlReferencedNames(variable.query).filter((name) => names.has(name) && (name !== variable.name || own))
}

export function orderVariables(variables: MetricsDashboardVariable[]): { order: string[]; cycle: string[] } {
    const parents = new Map(variables.map((variable) => [variable.name, variableParents(variable, variables)]))
    const order: string[] = []
    const placed = new Set<string>()
    let progress = true
    while (progress) {
        progress = false
        for (const variable of variables) {
            if (!placed.has(variable.name) && parents.get(variable.name)!.every((parent) => placed.has(parent))) {
                order.push(variable.name)
                placed.add(variable.name)
                progress = true
            }
        }
    }
    return { order, cycle: variables.map((variable) => variable.name).filter((name) => !placed.has(name)) }
}

export function dependentsOf(variables: MetricsDashboardVariable[], names: string[]): string[] {
    // Each query is read once, so a long chain of variables does not read the same queries again for each step.
    const children = new Map<string, string[]>()
    for (const variable of variables) {
        for (const parent of variableParents(variable, variables)) {
            children.set(parent, [...(children.get(parent) ?? []), variable.name])
        }
    }
    const found = new Set<string>()
    const queue = [...names]
    while (queue.length) {
        for (const child of children.get(queue.shift()!) ?? []) {
            if (!found.has(child)) {
                found.add(child)
                queue.push(child)
            }
        }
    }
    return [...found]
}

/** The variables to load again after a change: changed definitions, and everything that depends on a change. */
export function variablesToReload(previous: MetricsDashboardVariable[], next: MetricsDashboardVariable[]): string[] {
    const before = new Map(previous.map((variable) => [variable.name, variable]))
    const redefined: string[] = []
    const changed: string[] = []
    for (const variable of next) {
        const old = before.get(variable.name)
        const { current, ...definition } = variable
        if (!old) {
            redefined.push(variable.name)
            continue
        }
        const { current: oldCurrent, ...oldDefinition } = old
        if (!objectsEqual(definition, oldDefinition)) {
            redefined.push(variable.name)
        } else if (!objectsEqual(current ?? null, oldCurrent ?? null)) {
            changed.push(variable.name)
        }
    }
    return [...new Set([...redefined, ...dependentsOf(next, [...redefined, ...changed])])]
}

/** All keeps no values, so that a high-cardinality variable does not make the dashboard URL too long. */
export function reconcileSelection(
    variable: MetricsDashboardVariable,
    options: string[]
): MetricsDashboardVariableSelection | null {
    if (variable.source === 'textbox') {
        return variable.current ?? null
    }
    if (variable.current?.all && variable.includeAll) {
        return { values: [], all: true }
    }
    const kept = (variable.current?.values ?? []).filter((value) => options.includes(value))
    if (kept.length) {
        return { values: variable.multi ? kept : kept.slice(0, 1) }
    }
    return options.length ? { values: [options[0]] } : null
}

export function selectionFromValues(
    variable: MetricsDashboardVariable,
    values: string[],
    options: string[]
): MetricsDashboardVariableSelection | null {
    if (variable.includeAll) {
        const everyOption = variable.multi && options.length > 0 && options.every((option) => values.includes(option))
        if (values.includes(ALL_OPTION) || everyOption) {
            return { values: [], all: true }
        }
    }
    const picked = variable.includeAll ? values.filter((value) => value !== ALL_OPTION) : values
    return picked.length ? { values: picked } : null
}

/** The value that the record holds for the key itself, so a variable named `constructor` does not read `Object.prototype`. */
export function ownValue<T>(record: Record<string, T>, key: string): T | undefined {
    return Object.prototype.hasOwnProperty.call(record, key) ? record[key] : undefined
}

/** The selections that the options request of `variable` sends: only of the variables its query refers to.
 * All sends the loaded options to a SQL query, which needs them. PromQL matches everything without them. */
export function selectionsForRequest(
    variable: MetricsDashboardVariable,
    variables: MetricsDashboardVariable[],
    options: Record<string, string[]>
): _MetricVariableSelectionApi[] {
    const parents = new Set(variableParents(variable, variables))
    parents.delete(variable.name)
    return (
        variables
            .filter((other) => parents.has(other.name))
            .filter((other) => other.current && (other.current.values.length || other.current.all))
            // The server reads All as the options sent, so a SQL query waits until they load.
            .filter(
                (other) =>
                    !(
                        variable.source === 'sql' &&
                        other.current!.all &&
                        other.includeAll &&
                        !ownValue(options, other.name)
                    )
            )
            .map((other) => {
                const all = !!(other.current!.all && other.includeAll)
                return {
                    name: other.name,
                    values: all
                        ? variable.source === 'sql'
                            ? (ownValue(options, other.name) ?? [])
                            : []
                        : other.current!.values,
                    all,
                    allValue: other.allValue ?? null,
                }
            })
    )
}
