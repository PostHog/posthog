// What a push would change. The comparison decides whether the CLI writes at all, so it has two
// jobs that pull in opposite directions: see a real edit, and never see a change that is not one.
//
// A field PostHog derives is the trap. The server compiles bytecode into a filter and stamps keys
// the client never sent, so a plain deep compare reports every workflow as changed forever and
// every push writes a revision that says nothing. The rule: compare the fields the CLI sends,
// tolerate a key the server added inside a step's config, and stay strict everywhere the value is
// the customer's own.

import type { Action, WorkflowDefinition } from '../definition.js'
import type { SecretInput } from '../emit.js'

export interface Change {
    readonly kind: 'added' | 'removed' | 'changed'
    /** `status`, or `step "Wait a day"`. */
    readonly what: string
    readonly before?: string
    readonly after?: string
}

export interface Diff {
    readonly changed: boolean
    readonly changes: readonly Change[]
}

/** The fields the CLI sends. `key` identifies the row and `source` describes the push, so neither is content. */
const CONTENT_FIELDS = ['name', 'description', 'status', 'exit_condition'] as const

/** Keys PostHog derives from what it was sent, on either side of the comparison. */
const DERIVED_KEYS = new Set(['bytecode', 'bytecode_error', 'transpiled', 'order', 'secret'])

type Json = Record<string, unknown>

function isObject(value: unknown): value is Json {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function withoutDerived(value: Json): Json {
    return Object.fromEntries(Object.entries(value).filter(([key]) => !DERIVED_KEYS.has(key)))
}

/**
 * Deep equality. `tolerateExtra` marks the part of the tree PostHog owns, where it may add keys of
 * its own: extra keys on the remote side are ignored there, and the derived names are dropped from
 * both sides. Everywhere else the comparison is exact, because a key named `order` or `bytecode`
 * inside a value the customer wrote is the customer's, and dropping it would lose their edit.
 *
 * @param mine - The value from the local workflow file.
 * @param theirs - The value PostHog stores.
 * @param tolerateExtra - True inside the part of the tree PostHog owns, where extra remote keys are ignored.
 */
function same(mine: unknown, theirs: unknown, tolerateExtra: boolean): boolean {
    if (Array.isArray(mine) || Array.isArray(theirs)) {
        return (
            Array.isArray(mine) &&
            Array.isArray(theirs) &&
            mine.length === theirs.length &&
            mine.every((entry, index) => same(entry, theirs[index], tolerateExtra))
        )
    }
    if (isObject(mine) && isObject(theirs)) {
        const left = tolerateExtra ? withoutDerived(mine) : mine
        const right = tolerateExtra ? withoutDerived(theirs) : theirs
        if (!tolerateExtra && Object.keys(left).length !== Object.keys(right).length) {
            return false
        }
        return Object.entries(left).every(([key, value]) => key in right && same(value, right[key], tolerateExtra))
    }
    return mine === theirs
}

function inputsOf(config: unknown): Json {
    const inputs = isObject(config) ? config.inputs : undefined
    return isObject(inputs) ? inputs : {}
}

function configWithoutInputs(config: unknown): Json {
    if (!isObject(config)) {
        return {}
    }
    return Object.fromEntries(Object.entries(config).filter(([key]) => key !== 'inputs'))
}

/**
 * One step, with its secret inputs removed from both sides.
 *
 * PostHog reads a secret input back as a placeholder, so comparing it would report a change on
 * every run. The value is sent on every push instead, and `--force` is how a rotation that changes
 * nothing else still writes.
 *
 * @param mine - The step from the local workflow file.
 * @param theirs - The matching step PostHog stores.
 * @param secretKeys - Every `actionId.inputKey` that names a secret input.
 */
function sameAction(mine: Action, theirs: Json, secretKeys: ReadonlySet<string>): boolean {
    if (mine.type !== theirs.type || mine.name !== theirs.name) {
        return false
    }
    if (!same(configWithoutInputs(mine.config), configWithoutInputs(theirs.config), true)) {
        return false
    }
    const drop = (inputs: Json): Json =>
        Object.fromEntries(Object.entries(inputs).filter(([key]) => !secretKeys.has(`${mine.id}.${key}`)))
    const mineInputs = drop(inputsOf(mine.config))
    const theirInputs = drop(inputsOf(theirs.config))
    if (Object.keys(mineInputs).length !== Object.keys(theirInputs).length) {
        return false
    }
    // A secret input is only skipped while PostHog gives nothing back to compare, which is the
    // usual case: it reads a secret back as a placeholder, so a rotation is invisible here and
    // needs `--force`. When a readable value does come back, comparing it is what catches a
    // credential that was moved into an environment variable while the old one stayed live.
    for (const key of secretKeys) {
        const [actionId, inputKey] = key.split('.')
        if (actionId !== mine.id || inputKey === undefined) {
            continue
        }
        const stored = inputsOf(theirs.config)[inputKey]
        const storedValue = isObject(stored) ? stored.value : undefined
        if (typeof storedValue !== 'string' || storedValue === '') {
            continue
        }
        const local = inputsOf(mine.config)[inputKey]
        if (!isObject(local) || local.value !== storedValue) {
            return false
        }
    }
    // An input's value is the customer's own, so a key missing there is a real change.
    return Object.entries(mineInputs).every(([key, value]) => {
        const other = theirInputs[key]
        return isObject(value) && isObject(other) && same(value.value, other.value, false)
    })
}

function short(value: unknown): string {
    if (value === undefined || value === null) {
        return 'nothing'
    }
    const text = typeof value === 'string' ? value : JSON.stringify(value)
    if (text === undefined || text === '') {
        return 'empty'
    }
    return text.length > 70 ? `${text.slice(0, 67)}...` : text
}

/**
 * What a push would change, and whether it would write at all.
 *
 * Steps are matched by action id, which is the slug of the step name, so inserting a step reads as
 * one addition rather than a rewrite of everything after it.
 *
 * @param local - The workflow the file emitted.
 * @param remote - The workflow PostHog stores, as the API returned it.
 * @param secretInputs - The inputs the file reads from `secret()`, left out of the comparison.
 */
export function diffWorkflow(
    local: WorkflowDefinition,
    remote: Readonly<Record<string, unknown>>,
    secretInputs: readonly SecretInput[]
): Diff {
    const secretKeys = new Set(secretInputs.map((input) => `${input.actionId}.${input.inputKey}`))
    const changes: Change[] = []

    for (const field of CONTENT_FIELDS) {
        if (local[field] !== remote[field]) {
            changes.push({ kind: 'changed', what: field, before: short(remote[field]), after: short(local[field]) })
        }
    }

    if (!same(local.variables, remote.variables ?? [], true)) {
        changes.push({ kind: 'changed', what: 'variables' })
    }

    const theirActions = new Map<string, Json>(
        (Array.isArray(remote.actions) ? (remote.actions as Json[]) : [])
            .filter(isObject)
            .map((action) => [String(action.id), action])
    )
    for (const action of local.actions) {
        const theirs = theirActions.get(action.id)
        if (theirs === undefined) {
            changes.push({ kind: 'added', what: `step "${action.name}"` })
        } else if (!sameAction(action, theirs, secretKeys)) {
            changes.push({ kind: 'changed', what: `step "${action.name}"` })
        }
    }
    const mineIds = new Set(local.actions.map((action) => action.id))
    for (const [id, action] of theirActions) {
        if (!mineIds.has(id)) {
            changes.push({ kind: 'removed', what: `step "${String(action.name ?? id)}"` })
        }
    }

    if (!same(local.edges, remote.edges ?? [], false)) {
        changes.push({ kind: 'changed', what: 'the connections between steps' })
    }

    return { changed: changes.length > 0, changes }
}
