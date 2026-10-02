import type {
    EventsEnumApi,
    LoopDTOApi,
    LoopRepositoryEntryApi,
    LoopTriggerTypeEnumApi,
    LoopWriteApi,
    LoopWriteVisibilityEnumApi,
    ReasoningEffortEnumApi,
    RuntimeAdapterEnumApi,
} from '../../../generated/api.schemas'

// Mirrors PostHog Desktop's `loopFormTypes.ts`, so a loop saved from web reads the same in Desktop and the
// other way round. Web cannot bundle a skill from the local machine, so it only keeps or detaches a skill
// Desktop attached.

export type LoopGithubTriggerEvent = 'push' | 'pull_request' | 'issues' | 'issue_comment'

export interface LoopScheduleTriggerConfig {
    cron_expression?: string
    run_at?: string
    timezone?: string
}

export interface LoopGithubTriggerPayloadFilter {
    path: string
    equals: string | string[]
}

export interface LoopGithubTriggerFilters {
    actions?: string[]
    payload?: LoopGithubTriggerPayloadFilter[]
}

export interface LoopGithubTriggerConfig {
    github_integration_id: number
    repository: string
    events: LoopGithubTriggerEvent[]
    filters?: LoopGithubTriggerFilters
}

export type LoopApiTriggerConfig = Record<string, never>

export type LoopTriggerConfig = LoopScheduleTriggerConfig | LoopGithubTriggerConfig | LoopApiTriggerConfig

/**
 * A trigger row in the form. `key` is a client-only identity for list rendering, because a new row has no
 * server `id`. `id` is sent back on save, so the backend updates the row instead of adding a duplicate.
 */
export interface LoopTriggerDraft {
    key: string
    id?: string
    type: LoopTriggerTypeEnumApi
    enabled: boolean
    config: LoopTriggerConfig
}

export interface LoopNotificationChannel {
    enabled: boolean
    events: EventsEnumApi[]
    params: Record<string, unknown>
}

export interface LoopNotifications {
    push: LoopNotificationChannel
    email: LoopNotificationChannel
    slack: LoopNotificationChannel
}

export interface LoopBehaviors {
    create_prs: boolean
    watch_ci: boolean
    fix_review_comments: boolean
    max_fix_iterations: number
}

export interface LoopContextOutputs {
    post_to_feed: boolean
    update_context: boolean
    canvas_id: string | null
}

export interface LoopContextTargetDraft {
    spaceId: string
    name: string
    outputs: LoopContextOutputs
}

/** A skill a loop already runs. Only Desktop can attach one, because it bundles the skill from disk. */
export interface LoopAttachedSkill {
    name: string
    source: string
}

export interface LoopFormValues {
    name: string
    description: string
    visibility: LoopWriteVisibilityEnumApi
    instructions: string
    /** When set, the loop runs this skill, and the instructions become `/skill-name` plus `skillContext`. */
    skill: LoopAttachedSkill | null
    skillContext: string
    runtimeAdapter: RuntimeAdapterEnumApi
    model: string
    reasoningEffort: ReasoningEffortEnumApi | null
    /** The whole repository list. The form edits the first entry and keeps the others as they are. */
    repositories: LoopRepositoryEntryApi[]
    sandboxEnvironmentId: string | null
    triggers: LoopTriggerDraft[]
    behaviors: LoopBehaviors
    notifications: LoopNotifications
    contextTarget: LoopContextTargetDraft | null
    /** Team skills a workflow-backed loop attaches. The loops API ignores it. */
    teamSkills: string[]
}

export type LoopFormBackend = 'loops' | 'workflow'

export function systemTimezone(): string {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
}

/** The `action` values GitHub sends for each webhook event a loop can subscribe to. Push carries none. */
const GITHUB_EVENT_ACTIONS: Record<LoopGithubTriggerEvent, string[]> = {
    push: [],
    pull_request: [
        'opened',
        'reopened',
        'closed',
        'synchronize',
        'edited',
        'ready_for_review',
        'converted_to_draft',
        'review_requested',
        'review_request_removed',
        'labeled',
        'unlabeled',
        'assigned',
        'unassigned',
    ],
    issues: [
        'opened',
        'reopened',
        'closed',
        'edited',
        'deleted',
        'labeled',
        'unlabeled',
        'assigned',
        'unassigned',
        'pinned',
        'unpinned',
        'transferred',
    ],
    issue_comment: ['created', 'edited', 'deleted'],
}

/**
 * The actions every selected event can send. One action list is matched against every event on the trigger,
 * so an action only some events send would stop the others from firing.
 */
export function githubTriggerActionOptions(events: LoopGithubTriggerEvent[]): string[] {
    if (!events.length) {
        return []
    }
    return events
        .map((event) => GITHUB_EVENT_ACTIONS[event] ?? [])
        .reduce((shared, actions) => shared.filter((action) => actions.includes(action)))
}

const MODELLED_GITHUB_ACTIONS = new Set(Object.values(GITHUB_EVENT_ACTIONS).flat())

/**
 * Sets the trigger's events and drops a selected action the new events cannot all send. An action the form
 * does not know stays, because dropping it would widen the trigger without the person seeing a control for it.
 */
export function withGithubTriggerEvents(
    config: LoopGithubTriggerConfig,
    events: LoopGithubTriggerEvent[]
): LoopGithubTriggerConfig {
    const offerable = githubTriggerActionOptions(events)
    const actions = (config.filters?.actions ?? []).filter(
        (action) => offerable.includes(action) || !MODELLED_GITHUB_ACTIONS.has(action)
    )
    return withGithubTriggerFilters({ ...config, events }, { actions })
}

/** Applies a filter patch and drops keys that end up empty, so an untouched trigger stores no empty lists. */
export function withGithubTriggerFilters(
    config: LoopGithubTriggerConfig,
    patch: Partial<LoopGithubTriggerFilters>
): LoopGithubTriggerConfig {
    const merged = { ...config.filters, ...patch }
    const filters = Object.fromEntries(
        Object.entries(merged).filter(([, value]) => !Array.isArray(value) || value.length > 0)
    ) as LoopGithubTriggerFilters
    return { ...config, filters }
}

function defaultLoopNotifications(): LoopNotifications {
    return {
        push: { enabled: false, events: [], params: {} },
        email: { enabled: false, events: [], params: {} },
        slack: { enabled: false, events: [], params: {} },
    }
}

export function defaultLoopBehaviors(): LoopBehaviors {
    return { create_prs: true, watch_ci: false, fix_review_comments: false, max_fix_iterations: 3 }
}

/** Runs go to the space's feed, and context.md and canvases stay untouched until someone turns them on. */
export function defaultLoopContextOutputs(): LoopContextOutputs {
    return { post_to_feed: true, update_context: false, canvas_id: null }
}

/** One "Auto-fix pull requests" switch drives both CI watching and review comment fixes. */
export function isAutoFixEnabled(behaviors: LoopBehaviors): boolean {
    return behaviors.watch_ci && behaviors.fix_review_comments
}

export function withAutoFix(behaviors: LoopBehaviors, enabled: boolean): LoopBehaviors {
    return { ...behaviors, watch_ci: enabled, fix_review_comments: enabled }
}

let draftKeySeq = 0

export function nextDraftTriggerKey(): string {
    draftKeySeq += 1
    return `draft-trigger-${draftKeySeq}`
}

export function defaultLoopTriggerOfType(type: LoopTriggerTypeEnumApi): LoopTriggerDraft {
    const config: LoopTriggerConfig =
        type === 'schedule'
            ? { cron_expression: '0 9 * * 1', timezone: systemTimezone() }
            : type === 'github'
              ? { github_integration_id: 0, repository: '', events: [] }
              : {}
    return { key: nextDraftTriggerKey(), type, enabled: true, config }
}

export function emptyLoopFormValues(): LoopFormValues {
    return {
        name: '',
        description: '',
        visibility: 'personal',
        instructions: '',
        skill: null,
        skillContext: '',
        runtimeAdapter: 'claude',
        model: '',
        reasoningEffort: null,
        repositories: [],
        sandboxEnvironmentId: null,
        triggers: [defaultLoopTriggerOfType('schedule')],
        behaviors: defaultLoopBehaviors(),
        notifications: defaultLoopNotifications(),
        contextTarget: null,
        teamSkills: [],
    }
}

/** A loop in a space files its runs in the shared feed, so it is team-visible. The backend rejects personal. */
export function normalizeLoopFormValues(values: LoopFormValues): LoopFormValues {
    return values.contextTarget && values.visibility !== 'team' ? { ...values, visibility: 'team' } : values
}

export function buildSkillInstructions(skillName: string, context: string): string {
    const invocation = `/${skillName}`
    const trimmed = context.trim()
    return trimmed ? `${invocation}\n\n${trimmed}` : invocation
}

/** The text after the leading `/skill-name` line. Instructions in another shape come back whole. */
export function parseSkillContext(instructions: string, skillName: string): string {
    const invocation = `/${skillName}`
    const trimmed = instructions.trim()
    if (trimmed === invocation) {
        return ''
    }
    if (trimmed.startsWith(`${invocation}\n`)) {
        return trimmed.slice(invocation.length).trim()
    }
    return trimmed
}

function channel(
    value: { enabled?: boolean; events?: string[]; params?: Record<string, unknown> } | undefined
): LoopNotificationChannel {
    return {
        enabled: !!value?.enabled,
        events: (value?.events ?? []) as EventsEnumApi[],
        params: value?.params ?? {},
    }
}

export function loopToFormValues(loop: LoopDTOApi): LoopFormValues {
    const primaryBundle = loop.skill_bundles?.[0] ?? null
    return {
        name: loop.name,
        description: loop.description,
        visibility: loop.visibility === 'team' ? 'team' : 'personal',
        instructions: loop.instructions,
        skill: primaryBundle ? { name: primaryBundle.skill_name, source: primaryBundle.skill_source } : null,
        skillContext: primaryBundle ? parseSkillContext(loop.instructions, primaryBundle.skill_name) : '',
        runtimeAdapter: loop.runtime_adapter === 'codex' ? 'codex' : 'claude',
        model: loop.model,
        reasoningEffort: (loop.reasoning_effort as ReasoningEffortEnumApi | null) ?? null,
        repositories: loop.repositories.map(({ github_integration_id, full_name }) => ({
            github_integration_id,
            full_name,
        })),
        sandboxEnvironmentId: loop.sandbox_environment_id,
        triggers: loop.triggers.map((trigger) => ({
            key: trigger.id,
            id: trigger.id,
            type: trigger.type as LoopTriggerTypeEnumApi,
            enabled: trigger.enabled,
            config: trigger.config as LoopTriggerConfig,
        })),
        behaviors: { ...defaultLoopBehaviors(), ...loop.behaviors },
        notifications: {
            push: channel(loop.notifications.push),
            email: channel(loop.notifications.email),
            slack: channel(loop.notifications.slack),
        },
        contextTarget: loop.context_target
            ? {
                  spaceId: loop.context_target.channel_id,
                  name: loop.context_target.name,
                  outputs: { ...defaultLoopContextOutputs(), ...loop.context_target.outputs },
              }
            : null,
        teamSkills: [],
    }
}

/** Each accepted value is its own entry, never a delimited string, because a matchable value can hold a comma. */
function payloadConditionValues(condition: LoopGithubTriggerPayloadFilter): string[] {
    const values = Array.isArray(condition.equals) ? condition.equals : [condition.equals]
    return values.map((value) => value.trim()).filter(Boolean)
}

function withNormalizedPayloadConditions(config: LoopGithubTriggerConfig): LoopGithubTriggerConfig {
    const conditions = config.filters?.payload
    if (!conditions) {
        return config
    }
    return {
        ...config,
        filters: {
            ...config.filters,
            payload: conditions.map((condition) => ({
                path: condition.path.trim(),
                equals: payloadConditionValues(condition),
            })),
        },
    }
}

export function formValuesToLoopWrite(values: LoopFormValues): LoopWriteApi {
    return {
        name: values.name.trim(),
        description: values.description.trim(),
        visibility: values.visibility,
        instructions: values.skill
            ? buildSkillInstructions(values.skill.name, values.skillContext)
            : values.instructions,
        runtime_adapter: values.runtimeAdapter,
        model: values.model.trim(),
        reasoning_effort: values.reasoningEffort,
        repositories: values.repositories,
        sandbox_environment: values.sandboxEnvironmentId,
        triggers: values.triggers.map((trigger) => ({
            id: trigger.id,
            type: trigger.type,
            enabled: trigger.enabled,
            config:
                trigger.type === 'github'
                    ? withNormalizedPayloadConditions(trigger.config as LoopGithubTriggerConfig)
                    : trigger.config,
        })),
        behaviors: values.behaviors,
        notifications: values.notifications,
        context_target: values.contextTarget
            ? {
                  channel_id: values.contextTarget.spaceId,
                  name: values.contextTarget.name,
                  outputs: values.contextTarget.outputs,
              }
            : null,
    }
}

function isPayloadConditionValid(condition: LoopGithubTriggerPayloadFilter): boolean {
    return !!condition.path.trim() && payloadConditionValues(condition).length > 0
}

/**
 * Whether the trigger can be saved. A workflow resolves the GitHub repository itself, so it needs no
 * integration id, and it listens to one event type. The API trigger exists only in the loops API.
 */
export function isTriggerDraftValid(trigger: LoopTriggerDraft, backend: LoopFormBackend): boolean {
    if (trigger.type === 'schedule') {
        const config = trigger.config as LoopScheduleTriggerConfig
        return !!config.run_at || !!config.cron_expression
    }
    if (trigger.type === 'github') {
        const config = trigger.config as LoopGithubTriggerConfig
        const workflow = backend === 'workflow'
        return (
            !!config.repository &&
            (workflow || config.github_integration_id > 0) &&
            (workflow ? config.events.length === 1 : config.events.length > 0) &&
            (config.filters?.payload ?? []).every(isPayloadConditionValid)
        )
    }
    return backend !== 'workflow'
}

/** The loops API takes any trigger list, an empty one included. A workflow needs exactly one enabled trigger. */
export function isTriggerListValid(triggers: LoopTriggerDraft[], backend: LoopFormBackend): boolean {
    if (backend === 'workflow') {
        const [trigger, ...rest] = triggers
        if (!trigger || rest.length || !trigger.enabled) {
            return false
        }
    }
    return triggers.every((trigger) => isTriggerDraftValid(trigger, backend))
}

/** Why the form cannot be saved yet, or null when it can. */
export function loopFormInvalidReason(values: LoopFormValues, backend: LoopFormBackend): string | null {
    if (!values.name.trim()) {
        return 'Give the loop a name.'
    }
    if (!values.skill && !values.instructions.trim()) {
        return 'Write the instructions the agent runs.'
    }
    if (values.contextTarget && values.visibility !== 'team') {
        return 'A loop in a space must be visible to the team.'
    }
    if (!isTriggerListValid(values.triggers, backend)) {
        return backend === 'workflow' && values.triggers.length !== 1
            ? 'Add one trigger.'
            : 'Finish each trigger, or remove the ones you do not need.'
    }
    return null
}
