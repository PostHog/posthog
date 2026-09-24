// How PostHog stores a workflow it was sent, written as rules that both sides of a comparison go
// through. After the rules run the comparison is exact: a field PostHog stores as it was sent is
// compared as the author wrote it, so removing an authored field reads as a change.
//
// Every rule names its field. A key PostHog adds that no rule names makes the workflow read as
// changed on every push, which costs one needless revision. A rule that ignored every unknown key
// would instead hide an edit that then never deploys, so the tables stay explicit.

import type { Action, WorkflowDefinition } from '../definition.js'
import type { SecretInput } from '../emit.js'

type Json = Record<string, unknown>

type FieldRule =
    | 'identity'
    | 'exact'
    /** PostHog trims surrounding whitespace from the text when it saves. */
    | 'text'
    | 'optional text'
    /** PostHog stores null when a push leaves it out, so an empty value is the same setting. */
    | 'optional'
    | 'filters'
    /** Compared only when the file sets it, because PostHog owns the value otherwise. */
    | 'when authored'
    | 'config'
    | 'variables'
    | 'actions'
    | 'edges'

type KeysOf<T> = T extends unknown ? keyof T : never

// The mapped types make a field that the definition gains and these tables do not name a type
// error, so a new authored field cannot be left out of the comparison by accident.
const DEFINITION_FIELDS = {
    key: 'identity',
    name: 'text',
    description: 'optional text',
    exit_condition: 'exact',
    status: 'when authored',
    variables: 'variables',
    actions: 'actions',
    edges: 'edges',
} as const satisfies { readonly [K in keyof WorkflowDefinition]-?: FieldRule }

const ACTION_FIELDS = {
    id: 'identity',
    type: 'exact',
    name: 'text',
    description: 'optional text',
    filters: 'filters',
    on_error: 'optional',
    output_variable: 'optional',
    config: 'config',
} as const satisfies { readonly [K in KeysOf<Action>]-?: FieldRule }

const DEFAULTED_RULES: ReadonlySet<FieldRule> = new Set(['optional text', 'optional', 'filters'])

/**
 * Action fields PostHog fills when a push leaves them out: `description` becomes an empty string,
 * and `filters`, `on_error` and `output_variable` become null. Leaving one out of the file restores
 * that default, and an empty value compares equal to a missing one.
 */
export const DEFAULTED_ACTION_KEYS: ReadonlySet<string> = new Set(
    Object.entries(ACTION_FIELDS)
        .filter(([, rule]) => DEFAULTED_RULES.has(rule))
        .map(([key]) => key)
)

/** Action fields the PostHog editor stamps and a file never carries. */
export const DERIVED_ACTION_KEYS: ReadonlySet<string> = new Set(['created_at', 'updated_at'])

/** The compiled forms PostHog adds to a step config, at any depth outside an input value. */
export const COMPILED_CONFIG_KEYS: ReadonlySet<string> = new Set(['bytecode', 'bytecode_error', 'transpiled'])

/** Keys PostHog adds to every `filters` object: the compiled forms, and the event source it defaults. */
export const DERIVED_FILTER_KEYS: ReadonlySet<string> = new Set([...COMPILED_CONFIG_KEYS, 'source'])

/**
 * Keys PostHog adds to a function input beside its `value`: the compiled template, the order the
 * inputs evaluate in, and the `secret` mask it reads a stored secret back as.
 */
export const DERIVED_INPUT_KEYS: ReadonlySet<string> = new Set([...COMPILED_CONFIG_KEYS, 'order', 'secret'])

/** Values PostHog writes into a function input that leaves them out, taken from the template. */
export const INPUT_DEFAULTS: Readonly<Record<string, unknown>> = { templating: 'hog' }

/** Config values PostHog writes into a step of one type when the step leaves them out. */
export const CONFIG_DEFAULTS: Readonly<Record<string, Readonly<Record<string, unknown>>>> = {
    function_email: { template_id: 'template-email' },
    function_sms: { template_id: 'template-twilio' },
    function_push: { template_id: 'template-native-push' },
    wait_until_condition: { condition: { filters: null }, events: [] },
}

export type ContentField = 'name' | 'description' | 'exit_condition' | 'status' | 'variables'

export interface ActionChange {
    readonly id: string
    readonly kind: 'added' | 'removed' | 'changed'
}

export interface Comparison {
    readonly fields: readonly ContentField[]
    readonly actions: readonly ActionChange[]
    readonly edgesChanged: boolean
}

export interface SecretRules {
    readonly inputs: readonly SecretInput[]
    /** The secret inputs whose local value is real, so a value PostHog reads back can be compared. */
    readonly comparable: readonly SecretInput[]
}

type Side = 'local' | 'stored'

/**
 * A secret input after normalization. PostHog reads a stored secret back as a mask, so what both
 * sides can always compare is whether the secret is there. `value` is set only where it is known.
 */
class Secret {
    constructor(readonly value: string | undefined) {}
}

interface Context {
    readonly side: Side
    /** Secret input keys by action id. */
    readonly secrets: ReadonlyMap<string, ReadonlySet<string>>
    readonly comparable: ReadonlyMap<string, ReadonlySet<string>>
}

function isObject(value: unknown): value is Json {
    return typeof value === 'object' && value !== null && !Array.isArray(value) && !(value instanceof Secret)
}

function isEmpty(value: unknown): boolean {
    return (
        value === undefined ||
        value === null ||
        value === '' ||
        (Array.isArray(value) && value.length === 0) ||
        (isObject(value) && Object.keys(value).length === 0)
    )
}

function without(value: Json, keys: ReadonlySet<string>): Json {
    return Object.fromEntries(Object.entries(value).filter(([key]) => !keys.has(key)))
}

// Deep equality over normalized values. A key holding `undefined` counts as missing, and two
// secrets are equal when both are present and their values do not disagree.
function same(mine: unknown, theirs: unknown): boolean {
    if (mine instanceof Secret || theirs instanceof Secret) {
        return (
            mine instanceof Secret &&
            theirs instanceof Secret &&
            (mine.value === undefined || theirs.value === undefined || mine.value === theirs.value)
        )
    }
    if (Array.isArray(mine) || Array.isArray(theirs)) {
        return (
            Array.isArray(mine) &&
            Array.isArray(theirs) &&
            mine.length === theirs.length &&
            mine.every((entry, index) => same(entry, theirs[index]))
        )
    }
    if (isObject(mine) && isObject(theirs)) {
        const keys = new Set([...Object.keys(mine), ...Object.keys(theirs)])
        return [...keys].every((key) => same(mine[key], theirs[key]))
    }
    return mine === theirs
}

// `key` is the name the value sits under, because PostHog also sets the source on anything named
// `filters`.
function withoutCompiled(value: unknown, key?: string): unknown {
    if (Array.isArray(value)) {
        return value.map((entry) => withoutCompiled(entry))
    }
    if (!isObject(value)) {
        return value
    }
    const drop = key === 'filters' ? DERIVED_FILTER_KEYS : COMPILED_CONFIG_KEYS
    return Object.fromEntries(
        Object.entries(without(value, drop)).map(([name, entry]) => [name, withoutCompiled(entry, name)])
    )
}

function withoutDefaults(value: Json, defaults: Readonly<Record<string, unknown>>): Json {
    return Object.fromEntries(
        Object.entries(value).filter(([key, entry]) => !(key in defaults && same(entry, defaults[key])))
    )
}

// A secret the file names is always present locally, because emit refuses an unset one. PostHog
// reads a stored one back as `{ secret: true }`, and returns the value only where it stores it in
// the clear.
function secretInput(input: unknown, inputKey: string, actionId: string, context: Context): Secret | undefined {
    const value = isObject(input) ? input.value : undefined
    if (context.side === 'local') {
        const known = context.comparable.get(actionId)?.has(inputKey) === true && typeof value === 'string'
        return new Secret(known ? value : undefined)
    }
    if (!isObject(input) || (input.secret !== true && isEmpty(value))) {
        return undefined
    }
    return new Secret(typeof value === 'string' && value !== '' ? value : undefined)
}

function normalizeInputs(inputs: Json, actionId: string, context: Context): Json {
    const secretKeys = context.secrets.get(actionId)
    return Object.fromEntries(
        Object.entries(inputs).map(([key, input]) => {
            if (secretKeys?.has(key) === true) {
                return [key, secretInput(input, key, actionId, context)]
            }
            // The value is the customer's own, so nothing inside it is dropped.
            return [key, isObject(input) ? withoutDefaults(without(input, DERIVED_INPUT_KEYS), INPUT_DEFAULTS) : input]
        })
    )
}

function normalizeConfig(config: unknown, action: Json, context: Context): unknown {
    if (!isObject(config)) {
        return config
    }
    const { inputs, ...rest } = config
    const normalized = withoutDefaults(withoutCompiled(rest) as Json, CONFIG_DEFAULTS[String(action.type)] ?? {})
    if (inputs === undefined) {
        return normalized
    }
    return { ...normalized, inputs: isObject(inputs) ? normalizeInputs(inputs, String(action.id), context) : inputs }
}

function trimmed(value: unknown): unknown {
    return typeof value === 'string' ? value.trim() : value
}

function normalizeField(rule: FieldRule, value: unknown): unknown {
    switch (rule) {
        case 'text':
            return trimmed(value)
        case 'optional text':
        case 'optional': {
            const normal = trimmed(value)
            return isEmpty(normal) ? undefined : normal
        }
        case 'filters': {
            const normal = withoutCompiled(value, 'filters')
            return isEmpty(normal) ? undefined : normal
        }
        case 'variables':
            // Each variable is a map of strings, which PostHog trims like any other text.
            return Array.isArray(value)
                ? value.map((entry) =>
                      isObject(entry)
                          ? Object.fromEntries(Object.entries(entry).map(([key, text]) => [key, trimmed(text)]))
                          : entry
                  )
                : (value ?? [])
        default:
            return value
    }
}

function normalizeAction(action: Json, context: Context): Json {
    const normalized: Json = {}
    for (const [key, value] of Object.entries(action)) {
        const rule: FieldRule | undefined = (ACTION_FIELDS as Readonly<Record<string, FieldRule>>)[key]
        if (rule === 'identity' || DERIVED_ACTION_KEYS.has(key)) {
            continue
        }
        // A key no rule names is compared as stored, so a field PostHog learns to keep is seen.
        normalized[key] =
            rule === undefined
                ? value
                : rule === 'config'
                  ? normalizeConfig(value, action, context)
                  : normalizeField(rule, value)
    }
    return normalized
}

function actionsById(actions: unknown, context: Context): Map<string, Json> {
    const list = Array.isArray(actions) ? actions.filter(isObject) : []
    return new Map(list.map((action) => [String(action.id), normalizeAction(action, context)]))
}

// An edge is identified by what it connects, so the order PostHog stores the list in means nothing.
function edgeSet(edges: unknown): string[] {
    const list: unknown[] = Array.isArray(edges) ? edges : []
    return list
        .map((edge) =>
            JSON.stringify(isObject(edge) ? [edge.from, edge.to, edge.type, edge.index ?? null] : (edge ?? null))
        )
        .sort()
}

function byAction(inputs: readonly SecretInput[]): Map<string, Set<string>> {
    const map = new Map<string, Set<string>>()
    for (const input of inputs) {
        const keys = map.get(input.actionId) ?? new Set<string>()
        keys.add(input.inputKey)
        map.set(input.actionId, keys)
    }
    return map
}

/**
 * Which parts of the definition a push would change.
 *
 * @param local - The definition the file emitted.
 * @param stored - The workflow PostHog stores, as the API returned it.
 * @param secrets - The inputs the file reads from `secret()`, and which of them have a real value.
 */
export function compareDefinitions(
    local: WorkflowDefinition,
    stored: Readonly<Record<string, unknown>>,
    secrets: SecretRules
): Comparison {
    const secretKeys = byAction(secrets.inputs)
    const comparable = byAction(secrets.comparable)
    const mineContext: Context = { side: 'local', secrets: secretKeys, comparable }
    const theirContext: Context = { side: 'stored', secrets: secretKeys, comparable }
    const authored = local as unknown as Readonly<Record<string, unknown>>

    const fields: ContentField[] = []
    for (const [field, rule] of Object.entries(DEFINITION_FIELDS) as [keyof WorkflowDefinition, FieldRule][]) {
        if (rule === 'identity' || rule === 'actions' || rule === 'edges') {
            continue
        }
        if (rule === 'when authored' && authored[field] === undefined) {
            continue
        }
        if (!same(normalizeField(rule, authored[field]), normalizeField(rule, stored[field]))) {
            fields.push(field as ContentField)
        }
    }

    const mine = actionsById(local.actions, mineContext)
    const theirs = actionsById(stored.actions, theirContext)
    const actions: ActionChange[] = []
    for (const [id, action] of mine) {
        const other = theirs.get(id)
        if (other === undefined) {
            actions.push({ id, kind: 'added' })
        } else if (!same(action, other)) {
            actions.push({ id, kind: 'changed' })
        }
    }
    for (const id of theirs.keys()) {
        if (!mine.has(id)) {
            actions.push({ id, kind: 'removed' })
        }
    }

    return { fields, actions, edgesChanged: !same(edgeSet(local.edges), edgeSet(stored.edges)) }
}
