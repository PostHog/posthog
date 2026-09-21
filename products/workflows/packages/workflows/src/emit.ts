// Ids and edges are derived here and never written by an author, which is what keeps a
// branch index and the edge that carries it from drifting apart.

import type {
    Action,
    BranchCondition,
    Duration,
    Edge,
    ExitCondition,
    FunctionInputs,
    TriggerConfig,
    WorkflowDefinition,
    WorkflowStatus,
    WorkflowVariable,
} from './definition.js'
import { WorkflowError } from './errors.js'
import { isSecretRef, type Path, type Step } from './steps.js'

/** The trigger and the exit carry no author-written name, so their ids are fixed. */
const TRIGGER_ID = 'trigger_node'
const EXIT_ID = 'exit_node'
const RESERVED_IDS = new Set([TRIGGER_ID, EXIT_ID])

/** `HogFlowActionSerializer` bounds the id at 200 and the name at 400. */
const MAX_ACTION_ID_LENGTH = 200
const MAX_STEP_NAME_LENGTH = 400
const EXPLICIT_ID_PATTERN = /^[A-Za-z0-9_-]+$/

/** `HogFlowVariableSerializer` caps the whole list at this many bytes. */
const VARIABLES_MAX_BYTES = 5120

/**
 * The same alternation `nodejs/src/cdp/services/hogflows/duration.ts` uses, so the SDK
 * and the runtime cannot drift. It also matches linearly, where the obvious
 * `\d*\.?\d+` backtracks on a long value that does not match.
 */
const DURATION_PATTERN = /^([0-9]+(?:\.[0-9]+)?|\.[0-9]+)([dhms])$/

/** `MAX_VALUE_FOR_DURATION_UNIT` in `nodejs/src/cdp/services/hogflows/actions/delay.ts`. */
const MAX_VALUE_FOR_DURATION_UNIT = { d: 30, h: 24, m: 60, s: 60 } as const
const NEXT_LARGER_UNIT = { s: 'm', m: 'h', h: 'd' } as const

type DurationUnit = keyof typeof MAX_VALUE_FOR_DURATION_UNIT

/** The options `Workflow.emit` and `compile` take. */
export interface EmitOptions {
    /**
     * Where a `secret` reads its variable. Defaults to `process.env`.
     *
     * An object passed here replaces `process.env` rather than layering over it, so it
     * holds every variable the workflow names. That is what makes a test independent of
     * the ambient environment.
     */
    readonly env?: Readonly<Record<string, string | undefined>>
}

/**
 * One secret that emit resolved, named by where it landed in the definition.
 *
 * A diff against PostHog excludes these keys on both sides, because a read returns the
 * placeholder `{"secret": true}` rather than the value, so a workflow holding a secret
 * would otherwise never compare equal and every push would report a change.
 */
export interface SecretInput {
    /** The action that holds the input. */
    readonly actionId: string
    /** The input key inside that action's config. */
    readonly inputKey: string
    /** The environment variable the value came from. */
    readonly envName: string
}

/** What `Workflow.emit` and `compile` return. */
export interface EmitResult {
    /** The JSON body to push. */
    readonly definition: WorkflowDefinition
    /** Every secret the emit resolved, in the order it resolved them. */
    readonly secretInputs: readonly SecretInput[]
}

/**
 * The options `compile` takes.
 *
 * These are `WorkflowOptions` with the trigger under its emitted name. Prefer
 * `workflow`, which is the authoring surface; `compile` exists for a caller that already
 * holds a trigger config and a path.
 */
export interface CompileOptions {
    readonly key: string
    readonly name: string
    readonly description?: string
    readonly status?: WorkflowStatus
    readonly exitCondition?: ExitCondition
    readonly variables?: readonly WorkflowVariable[]
    /** What starts a run. Build it with `onEvent` or `onSchedule`. */
    readonly trigger: TriggerConfig
    readonly steps: Path
    readonly exit: { readonly reason: string }
}

function slug(name: string): string {
    return name
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '_')
        .replace(/^_+|_+$/g, '')
}

/** One step at one place in the graph, with the action id it took. */
interface Placement {
    readonly step: Step
    readonly id: string
    /** A branch's sub-paths, already placed. Absent on every other kind. */
    readonly branches?: readonly (readonly Placement[])[]
}

/**
 * Hands out one action id per placement, in graph order.
 *
 * The id is the slug of the step name, so it survives an insertion or a reorder and
 * moves only on a rename, which a reviewer sees in the diff. PostHog keys a workflow's
 * in-flight participants and its secrets on the action id, so a shared id is refused
 * rather than made unique behind the author's back. One step value placed a second
 * time is the exception, because it is the same step, so the later placement in graph
 * order takes a numbered id.
 */
class Ids {
    private readonly baseOwner = new Map<string, Placed>()
    private readonly idOwner = new Map<string, Placed>()
    private readonly counts = new Map<string, number>()
    private position = 0

    next(step: Step): string {
        this.position += 1
        const placed: Placed = { step, position: this.position }
        const base = step.id === undefined ? this.derivedBase(step) : this.explicitBase(step, step.id)

        this.refuseReserved(base, step)
        this.refuseTaken(this.baseOwner, base, placed)
        this.baseOwner.set(base, placed)

        const seen = (this.counts.get(base) ?? 0) + 1
        this.counts.set(base, seen)
        const id = seen === 1 ? base : `${base}_${seen}`

        this.refuseLength(id, step)
        this.refuseReserved(id, step)
        this.refuseTaken(this.idOwner, id, placed)
        this.idOwner.set(id, placed)
        return id
    }

    private derivedBase(step: Step): string {
        if (step.name.length > MAX_STEP_NAME_LENGTH) {
            throw new WorkflowError({
                status: 'step_name_too_long',
                message: `A step name is ${step.name.length} characters, and the limit is ${MAX_STEP_NAME_LENGTH}.`,
                why: 'PostHog stores the step name in a field of that length, so a longer name fails the push.',
                fix: 'Shorten the name, and put the detail in the workflow description.',
            })
        }
        const base = slug(step.name)
        if (base === '') {
            throw new WorkflowError({
                status: 'unnamed_action_id',
                message: `The step name "${step.name}" produces no action id.`,
                why: 'An action id is the slug of the step name, and this name holds no letters or digits that a slug keeps.',
                fix: 'Give the step an explicit id.',
            })
        }
        return base
    }

    private explicitBase(step: Step, id: string): string {
        if (EXPLICIT_ID_PATTERN.test(id) && id.length <= MAX_ACTION_ID_LENGTH) {
            return id
        }
        throw new WorkflowError({
            status: 'invalid_action_id',
            message: `Step "${step.name}" sets the action id "${id}", which PostHog does not accept.`,
            why: `An action id holds letters, digits, hyphens and underscores, is not empty, and is at most ${MAX_ACTION_ID_LENGTH} characters.`,
            fix: 'Change the id to letters, digits, hyphens and underscores.',
        })
    }

    private refuseLength(id: string, step: Step): void {
        if (id.length <= MAX_ACTION_ID_LENGTH) {
            return
        }
        throw new WorkflowError({
            status: 'action_id_too_long',
            message: `Step "${step.name}" produces the action id "${id}", which is ${id.length} characters.`,
            why: `PostHog bounds an action id at ${MAX_ACTION_ID_LENGTH} characters, because the id is copied into every edge and into the redirect map.`,
            fix: 'Shorten the step name, or give the step an explicit id.',
        })
    }

    private refuseReserved(id: string, step: Step): void {
        if (!RESERVED_IDS.has(id)) {
            return
        }
        throw new WorkflowError({
            status: 'reserved_action_id',
            message: `Step "${step.name}" takes the action id "${id}", which is reserved.`,
            why: `Every workflow has a trigger node and an exit node, and they always use the ids "${TRIGGER_ID}" and "${EXIT_ID}".`,
            fix: 'Rename the step, or give it an explicit id.',
        })
    }

    private refuseTaken(owners: Map<string, Placed>, id: string, placed: Placed): void {
        const owner = owners.get(id)
        if (owner === undefined || owner.step === placed.step) {
            return
        }
        const both = owner.step.id !== undefined && placed.step.id !== undefined
        const where = `Step ${owner.position} ("${owner.step.name}") and step ${placed.position} ("${placed.step.name}") in graph order`
        const keying =
            "PostHog keys a workflow's in-flight participants and its secrets on the action id, so two steps cannot share one."
        throw new WorkflowError({
            status: 'duplicate_action_id',
            message: both ? `Two steps are given the action id "${id}".` : `Two steps produce the action id "${id}".`,
            why: both
                ? `${where} both set it. ${keying}`
                : `An action id is the slug of the step name. ${where} produce the same id. ${keying}`,
            fix: both ? 'Change the id on one of them.' : 'Rename one of the steps, or give one an explicit id.',
        })
    }
}

interface Placed {
    readonly step: Step
    readonly position: number
}

function checkDuration(duration: Duration, step: Step): void {
    const match = DURATION_PATTERN.exec(duration)
    if (match === null) {
        throw new WorkflowError({
            status: 'invalid_duration',
            message: `Step "${step.name}" waits for "${duration}", which is not a duration.`,
            why: 'A wait is a positive number and one of the units s, m, h or d, for example "30m" or "1.5d".',
            fix: `Change "${duration}" to a number and a unit.`,
        })
    }
    const amount = Number.parseFloat(match[1]!)
    const unit = match[2] as DurationUnit
    if (amount === 0) {
        throw new WorkflowError({
            status: 'invalid_duration',
            message: `Step "${step.name}" waits for "${duration}", which is no wait at all.`,
            why: 'A wait of zero adds a step that does nothing, which is almost always a typo.',
            fix: 'Set a wait above zero, or remove the step.',
        })
    }

    const cap = MAX_VALUE_FOR_DURATION_UNIT[unit]
    if (amount <= cap) {
        return
    }
    const larger = unit === 'd' ? undefined : NEXT_LARGER_UNIT[unit]
    throw new WorkflowError({
        status: 'duration_over_unit_cap',
        message: `Step "${step.name}" waits for "${duration}", and a wait in ${unitName(unit)} is capped at ${cap}.`,
        why: `PostHog clamps the amount to the cap for its unit and reports nothing, so this step would wait ${cap}${unit} instead.`,
        fix:
            larger === undefined
                ? 'The longest wait PostHog supports is 30d. Split the wait across two steps.'
                : `Use the larger unit: write "${amount / cap}${larger}".`,
    })
}

function unitName(unit: DurationUnit): string {
    return { d: 'days', h: 'hours', m: 'minutes', s: 'seconds' }[unit]
}

// The byte length the serializer measures, which is Python's `json.dumps`: a space
// after every separator, and every non-ASCII character escaped. Counting the shorter
// JavaScript form here would pass a file that the API then refuses.
function serializedSize(variable: WorkflowVariable): number {
    const escape = (value: string): string =>
        JSON.stringify(value).replace(
            /[\u007f-￿]/g,
            (character) => `\\u${character.charCodeAt(0).toString(16).padStart(4, '0')}`
        )
    const pairs = Object.entries(variable).map(([key, value]) => `${escape(key)}: ${escape(String(value))}`)
    return `{${pairs.join(', ')}}`.length
}

function checkVariables(variables: readonly WorkflowVariable[]): void {
    const seen = new Set<string>()
    for (const variable of variables) {
        if (seen.has(variable.key)) {
            throw new WorkflowError({
                status: 'duplicate_variable_key',
                message: `The workflow declares the variable "${variable.key}" two times.`,
                why: 'A run looks a variable up by its key, so two variables with one key have no defined value.',
                fix: `Remove one of the "${variable.key}" entries, or rename it.`,
            })
        }
        seen.add(variable.key)
    }

    const total = variables.reduce((size, variable) => size + serializedSize(variable), 0)
    if (total > VARIABLES_MAX_BYTES) {
        throw new WorkflowError({
            status: 'variables_too_large',
            message: `The variables add up to ${total} bytes, and the limit is ${VARIABLES_MAX_BYTES}.`,
            why: 'PostHog carries the variables with every run of the workflow, so the whole list is capped.',
            fix: 'Shorten the defaults, or move the long values into the step that uses them.',
        })
    }
}

// Walks a value rather than searching its JSON, so a string holding `__secret` is not
// a false match.
function holdsSecret(value: unknown, seen = new Set<unknown>()): boolean {
    if (isSecretRef(value)) {
        return true
    }
    if (typeof value !== 'object' || value === null || seen.has(value)) {
        return false
    }
    seen.add(value)
    return Object.values(value).some((entry) => holdsSecret(entry, seen))
}

// A secret inside a value would reach PostHog as the name of the variable, not its value.
function refuseNestedSecret(value: unknown, key: string, step: Step): void {
    if (!holdsSecret(value)) {
        return
    }
    throw new WorkflowError({
        status: 'nested_secret',
        message: `Step "${step.name}" puts a secret inside "${key}".`,
        why: 'Only a whole input can be a secret. Inside a value the name of the environment variable, not its value, would reach PostHog.',
        fix: `Pass secret('NAME') as the value of "${key}" itself, or move that part of the value into its own input.`,
    })
}

interface Context {
    readonly actions: Action[]
    readonly edges: Edge[]
    readonly secretInputs: SecretInput[]
    readonly env: Readonly<Record<string, string | undefined>>
}

function resolveInputs(step: Step & { kind: 'function' }, actionId: string, context: Context): FunctionInputs {
    const resolved: Record<string, { value: unknown }> = {}
    for (const [key, raw] of Object.entries(step.inputs)) {
        if (!isSecretRef(raw)) {
            refuseNestedSecret(raw, key, step)
            resolved[key] = { value: raw }
            continue
        }
        const value = context.env[raw.__secret]
        if (value === undefined || value === '') {
            throw new WorkflowError({
                status: 'missing_secret',
                message: `The environment variable ${raw.__secret} is not set or is empty.`,
                why: `Step "${step.name}" names ${raw.__secret} for the secret input "${key}". A secret is always sent rather than read back from PostHog, so there is nothing to send.`,
                fix: `Set ${raw.__secret} in the environment that runs the push, then push again.`,
            })
        }
        resolved[key] = { value }
        context.secretInputs.push({ actionId, inputKey: key, envName: raw.__secret })
    }
    return resolved
}

// Assigns an id to every placement, depth first, so the order matches the order a
// reader walks the graph. Allocating a whole path before its branches would let a step
// appended to the trunk take the id of a placement inside an earlier branch.
function place(steps: readonly Step[], ids: Ids, inBranch: boolean): Placement[] {
    if (steps.length === 0) {
        throw new WorkflowError({
            status: 'empty_path',
            message: inBranch ? 'A branch has an empty path.' : 'The workflow has no steps.',
            why: inBranch
                ? 'An empty branch path sends the branch to the same step as the no-match path, so the branch decides nothing.'
                : 'A workflow with no steps runs the trigger and exits at once.',
            fix: inBranch ? 'Put at least one step in the branch, or remove the branch.' : 'Add at least one step.',
        })
    }
    return steps.map((step) => {
        const id = ids.next(step)
        if (step.kind === 'branch') {
            return { step, id, branches: step.branches.map((spec) => place(spec.then, ids, true)) }
        }
        return { step, id }
    })
}

// Returns the id of the path's first node, which the caller needs for the edge into it.
function emitPath(placements: readonly Placement[], continuation: string, context: Context): string {
    placements.forEach((placement, position) => {
        const { step, id } = placement
        const next = placements[position + 1]?.id ?? continuation

        if (step.kind === 'delay') {
            checkDuration(step.duration, step)
            context.actions.push({ id, name: step.name, type: 'delay', config: { delay_duration: step.duration } })
            context.edges.push({ from: id, to: next, type: 'continue' })
            return
        }

        if (step.kind === 'function') {
            context.actions.push({
                id,
                name: step.name,
                type: 'function',
                config: { template_id: step.templateId, inputs: resolveInputs(step, id, context) },
            })
            context.edges.push({ from: id, to: next, type: 'continue' })
            return
        }

        if (step.kind === 'email') {
            // `template-email` has no secret input, so a secret here can only be a mistake.
            refuseNestedSecret(step.email, 'the email', step)
            context.actions.push({
                id,
                name: step.name,
                type: 'function_email',
                config: { template_id: 'template-email', inputs: { email: { value: step.email } } },
            })
            context.edges.push({ from: id, to: next, type: 'continue' })
            return
        }

        const conditions: BranchCondition[] = step.branches.map((spec) => ({
            name: spec.name,
            filters: { properties: [...spec.when] },
        }))
        context.actions.push({ id, name: step.name, type: 'conditional_branch', config: { conditions } })
        // The fall-through edge is the no-match path out of the branch.
        context.edges.push({ from: id, to: next, type: 'continue' })

        placement.branches?.forEach((sub, index) => {
            // The index and its edge come from the same array position, so they agree.
            const entry = emitPath(sub, next, context)
            context.edges.push({ from: id, to: entry, type: 'branch', index })
        })
    })

    return placements[0]?.id ?? continuation
}

/**
 * Turns a trigger and a path into the definition a push sends.
 *
 * `workflow(...).emit()` calls this, and that is the surface to use. Call `compile`
 * directly only when the trigger config and the path are already in hand.
 *
 * @param options - The workflow's identity, trigger, steps and exit.
 * @param emitOptions - Where to read a `secret` from. Defaults to `process.env`.
 * @returns The definition, and the secret inputs it resolved.
 * @throws {WorkflowError} The first rule the workflow breaks. The statuses are
 * `duplicate_action_id`, `reserved_action_id`, `invalid_action_id`,
 * `action_id_too_long`, `unnamed_action_id`, `step_name_too_long`, `invalid_duration`,
 * `duration_over_unit_cap`, `empty_path`, `missing_secret`, `nested_secret`,
 * `duplicate_variable_key` and `variables_too_large`.
 * @example
 * ```ts
 * import { compile, delay, onSchedule, path } from '@posthog/workflows'
 *
 * // Replace this key with your own before you push.
 * const { definition } = compile({
 *     key: 'replace-me-cool-off',
 *     name: 'Cool off',
 *     trigger: onSchedule(),
 *     steps: path(delay('1d', { name: 'Wait a day' })),
 *     exit: { reason: 'Done' },
 * })
 *
 * const ids = definition.actions.map((action) => action.id)
 * ```
 */
export function compile(options: CompileOptions, emitOptions: EmitOptions = {}): EmitResult {
    const variables = options.variables ?? []
    checkVariables(variables)

    const context: Context = {
        actions: [],
        edges: [],
        secretInputs: [],
        env: emitOptions.env ?? process.env,
    }

    const placements = place(options.steps, new Ids(), false)
    const entry = emitPath(placements, EXIT_ID, context)

    context.actions.unshift({ id: TRIGGER_ID, name: 'Trigger', type: 'trigger', config: options.trigger })
    context.edges.unshift({ from: TRIGGER_ID, to: entry, type: 'continue' })
    context.actions.push({ id: EXIT_ID, name: 'Exit', type: 'exit', config: { reason: options.exit.reason } })

    // Copied on the way out, so a caller that edits the definition cannot reach back into
    // the step values the file exports and change what a second emit produces.
    const definition: WorkflowDefinition = structuredClone({
        key: options.key,
        name: options.name,
        description: options.description ?? '',
        status: options.status ?? 'draft',
        exit_condition: options.exitCondition ?? 'exit_only_at_end',
        variables,
        actions: context.actions,
        edges: context.edges,
    })

    return { definition, secretInputs: context.secretInputs }
}
