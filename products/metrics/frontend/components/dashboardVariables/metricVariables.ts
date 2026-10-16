import { RE2JS } from 're2js'

import { objectsEqual } from 'lib/utils/objects'

import type { MetricsDashboardVariable, MetricsDashboardVariableSelection } from '~/queries/schema/schema-general'

import type { _MetricVariableSelectionApi } from 'products/metrics/frontend/generated/api.schemas'

/** The select value that stands for All. Grafana uses the same text. */
export const ALL_OPTION = '$__all'
export const VARIABLE_NAME = /^[A-Za-z_][A-Za-z0-9_]*$/
const REFERENCE =
    /\$\{([A-Za-z0-9_]+)(?::[A-Za-z0-9_]+)?\}|\[\[([A-Za-z0-9_]+)(?::[A-Za-z0-9_]+)?\]\]|\$([A-Za-z0-9_]+)/g

export function referencedNames(text: string | null | undefined): string[] {
    const names = new Set<string>()
    for (const match of (text ?? '').matchAll(REFERENCE)) {
        names.add(match[1] ?? match[2] ?? match[3])
    }
    return [...names]
}

/** The variables that a variable's options query refers to. A query that refers to its own variable is a loop. */
export function variableParents(variable: MetricsDashboardVariable, variables: MetricsDashboardVariable[]): string[] {
    if (variable.source !== 'promql' && variable.source !== 'sql') {
        return []
    }
    const names = new Set(variables.map((other) => other.name))
    return referencedNames(variable.query).filter((name) => names.has(name))
}

/** The variable names in an order where each variable comes after the variables its query refers to. */
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

/** The variables whose options depend on any of `names`, directly or through other variables. */
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

/** Keeps the options that match the variable's regex. With a capture group, the option is the first group.

RE2 runs the pattern in linear time, so a saved pattern cannot freeze the dashboard. A pattern that RE2 cannot read keeps every option. */
export function applyVariableRegex(options: string[], regex: string | null | undefined): string[] {
    if (!regex) {
        return options
    }
    // Grafana writes the pattern as /pattern/flags.
    const slashed = /^\/(.*)\/([a-z]*)$/s.exec(regex)
    const flags = slashed?.[2] ?? ''
    let pattern: RE2JS
    try {
        pattern = RE2JS.compile(
            slashed ? slashed[1] : regex,
            (flags.includes('i') ? RE2JS.CASE_INSENSITIVE : 0) |
                (flags.includes('m') ? RE2JS.MULTILINE : 0) |
                (flags.includes('s') ? RE2JS.DOTALL : 0)
        )
    } catch {
        return options
    }
    const matched: string[] = []
    for (const option of options) {
        const matcher = pattern.matcher(option)
        if (matcher.find()) {
            matched.push(matcher.groupCount() > 0 ? (matcher.group(1) ?? option) : option)
        }
    }
    return [...new Set(matched)]
}

/** The selection after the options change: a value that is gone is replaced.

All keeps no values, so a high-cardinality variable does not make the dashboard URL too long. */
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

/** The selection for the values picked in a select. Picking every option of a variable with All means All. */
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
