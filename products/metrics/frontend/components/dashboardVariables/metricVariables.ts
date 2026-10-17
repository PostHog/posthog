import { RE2JS } from 're2js'

import { objectsEqual } from 'lib/utils/objects'

import type { MetricsDashboardVariable, MetricsDashboardVariableSelection } from '~/queries/schema/schema-general'

import type { _MetricVariableSelectionApi } from 'products/metrics/frontend/generated/api.schemas'

/** The select value that stands for All. Grafana uses the same text. */
export const ALL_OPTION = '$__all'
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
            const end = text.indexOf('\n', index)
            index = end < 0 ? text.length : end
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
    const referenced = variable.source === 'sql' ? sqlReferencedNames(variable.query) : referencedNames(variable.query)
    return referenced.filter((name) => names.has(name))
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
    const found = new Set<string>()
    const queue = [...names]
    while (queue.length) {
        const name = queue.shift()!
        for (const variable of variables) {
            if (!found.has(variable.name) && variableParents(variable, variables).includes(name)) {
                found.add(variable.name)
                queue.push(variable.name)
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

/** RE2 runs the pattern in linear time, so a saved pattern cannot freeze the dashboard. Throws for an invalid pattern. */
export function compileVariableRegex(regex: string | null | undefined): RE2JS | null {
    const pattern = regex?.trim()
    if (!pattern) {
        return null
    }
    // Grafana writes the pattern as /pattern/flags.
    const slashed = /^\/(.*)\/([a-z]*)$/s.exec(pattern)
    const flags = slashed?.[2] ?? ''
    return RE2JS.compile(
        slashed ? slashed[1] : pattern,
        (flags.includes('i') ? RE2JS.CASE_INSENSITIVE : 0) |
            (flags.includes('m') ? RE2JS.MULTILINE : 0) |
            (flags.includes('s') ? RE2JS.DOTALL : 0)
    )
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
    const picked = values.filter((value) => value !== ALL_OPTION)
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
    return variables
        .filter((other) => parents.has(other.name))
        .filter((other) => other.current && (other.current.values.length || other.current.all))
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
}
