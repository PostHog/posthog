import type {
    LoopBehaviorsApi,
    LoopDTOApi,
    LoopRepositoryEntryApi,
    LoopTriggerDTOApi,
    LoopTriggerWriteApi,
    LoopWriteApi,
    LoopWriteVisibilityEnumApi,
    PatchedLoopWriteApi,
} from '../generated/api.schemas'

export const NEW_LOOP_ID = 'new'

export type LoopScheduleFrequency = 'hourly' | 'daily' | 'weekdays' | 'weekly'

export interface LoopSchedule {
    frequency: LoopScheduleFrequency
    /** `HH:MM`, 24-hour clock. */
    time: string
    /** Cron day of week, `0` (Sunday) to `6`. */
    weekday: string
}

/** How the loop starts. `null` means its triggers are more than this form can show, so a save leaves them as they are. */
export type LoopTriggerMode = 'schedule' | 'manual' | 'api'

export interface LoopFormValues {
    name: string
    instructions: string
    visibility: LoopWriteVisibilityEnumApi
    repository: LoopRepositoryEntryApi | null
    triggerMode: LoopTriggerMode | null
    /** Id of the trigger the form edits, so a save updates it in place and keeps its history. */
    triggerId: string | null
    schedule: LoopSchedule
    timezone: string
    createPullRequests: boolean
    autoFixPullRequests: boolean
}

export const DEFAULT_LOOP_SCHEDULE: LoopSchedule = { frequency: 'weekly', time: '09:00', weekday: '1' }

const DEFAULT_LOOP_BEHAVIORS: Required<LoopBehaviorsApi> = {
    create_prs: true,
    watch_ci: false,
    fix_review_comments: false,
    max_fix_iterations: 3,
}

export const WEEKDAY_NAMES: Record<string, string> = {
    '0': 'Sunday',
    '1': 'Monday',
    '2': 'Tuesday',
    '3': 'Wednesday',
    '4': 'Thursday',
    '5': 'Friday',
    '6': 'Saturday',
}

export function browserTimezone(): string {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
}

/** Reads only the cron shapes `compileCronSchedule` writes. Anything else is a custom schedule and returns null. */
export function parseCronSchedule(cron: string | null | undefined): LoopSchedule | null {
    const parts = cron?.trim().split(/\s+/) ?? []
    if (parts.length !== 5) {
        return null
    }
    const [minute, hour, dayOfMonth, month, dayOfWeek] = parts
    if (dayOfMonth !== '*' || month !== '*' || !/^\d{1,2}$/.test(minute) || Number(minute) > 59) {
        return null
    }
    if (hour === '*') {
        return minute === '0' && dayOfWeek === '*' ? { ...DEFAULT_LOOP_SCHEDULE, frequency: 'hourly' } : null
    }
    if (!/^\d{1,2}$/.test(hour) || Number(hour) > 23) {
        return null
    }
    const time = `${hour.padStart(2, '0')}:${minute.padStart(2, '0')}`
    if (dayOfWeek === '*') {
        return { frequency: 'daily', time, weekday: DEFAULT_LOOP_SCHEDULE.weekday }
    }
    if (dayOfWeek === '1-5') {
        return { frequency: 'weekdays', time, weekday: DEFAULT_LOOP_SCHEDULE.weekday }
    }
    return /^[0-6]$/.test(dayOfWeek) ? { frequency: 'weekly', time, weekday: dayOfWeek } : null
}

export function compileCronSchedule({ frequency, time, weekday }: LoopSchedule): string {
    const [hourPart, minutePart] = time.split(':')
    const hour = Number(hourPart) || 0
    const minute = Number(minutePart) || 0
    switch (frequency) {
        case 'hourly':
            return '0 * * * *'
        case 'daily':
            return `${minute} ${hour} * * *`
        case 'weekdays':
            return `${minute} ${hour} * * 1-5`
        case 'weekly':
            return `${minute} ${hour} * * ${weekday}`
    }
}

function scheduleConfig(trigger: LoopTriggerDTOApi): { cron_expression?: string; timezone?: string; run_at?: string } {
    return trigger.config as { cron_expression?: string; timezone?: string; run_at?: string }
}

interface EditableTrigger {
    mode: LoopTriggerMode
    trigger: LoopTriggerDTOApi | null
    schedule: LoopSchedule | null
}

/** The form edits one enabled schedule or API trigger, or none. GitHub, one-time and custom-cron triggers stay as they are. */
function editableTrigger(triggers: LoopTriggerDTOApi[]): EditableTrigger | null {
    if (triggers.length === 0) {
        return { mode: 'manual', trigger: null, schedule: null }
    }
    const [trigger, ...rest] = triggers
    if (rest.length > 0 || !trigger.enabled) {
        return null
    }
    if (trigger.type === 'api') {
        return { mode: 'api', trigger, schedule: null }
    }
    if (trigger.type === 'schedule') {
        const schedule = parseCronSchedule(scheduleConfig(trigger).cron_expression)
        return schedule ? { mode: 'schedule', trigger, schedule } : null
    }
    return null
}

export function emptyLoopFormValues(): LoopFormValues {
    return {
        name: '',
        instructions: '',
        visibility: 'personal',
        repository: null,
        triggerMode: 'schedule',
        triggerId: null,
        schedule: DEFAULT_LOOP_SCHEDULE,
        timezone: browserTimezone(),
        createPullRequests: DEFAULT_LOOP_BEHAVIORS.create_prs,
        autoFixPullRequests: false,
    }
}

export function loopToFormValues(loop: LoopDTOApi): LoopFormValues {
    const editable = editableTrigger(loop.triggers)
    const scheduleTrigger = loop.triggers.find((trigger) => trigger.type === 'schedule')
    return {
        name: loop.name,
        instructions: loop.instructions,
        visibility: loop.visibility === 'team' ? 'team' : 'personal',
        repository: loop.repositories[0] ?? null,
        triggerMode: editable?.mode ?? null,
        triggerId: editable?.trigger?.id ?? null,
        schedule: editable?.schedule ?? DEFAULT_LOOP_SCHEDULE,
        timezone: (scheduleTrigger && scheduleConfig(scheduleTrigger).timezone) || browserTimezone(),
        createPullRequests: loop.behaviors.create_prs ?? DEFAULT_LOOP_BEHAVIORS.create_prs,
        autoFixPullRequests: !!loop.behaviors.watch_ci && !!loop.behaviors.fix_review_comments,
    }
}

function triggersWrite(values: LoopFormValues): LoopTriggerWriteApi[] | undefined {
    const id = values.triggerId ?? undefined
    switch (values.triggerMode) {
        case null:
            return undefined
        case 'manual':
            return []
        case 'api':
            return [{ id, type: 'api', enabled: true, config: {} }]
        case 'schedule':
            return [
                {
                    id,
                    type: 'schedule',
                    enabled: true,
                    config: { cron_expression: compileCronSchedule(values.schedule), timezone: values.timezone },
                },
            ]
    }
}

export function formValuesToLoopWrite(values: LoopFormValues, behaviors?: LoopBehaviorsApi): LoopWriteApi {
    // The form has one switch for two settings. Keep a mixed pair set elsewhere until someone uses the switch.
    const keepAutoFix =
        !!behaviors && values.autoFixPullRequests === (!!behaviors.watch_ci && !!behaviors.fix_review_comments)
    return {
        name: values.name.trim(),
        instructions: values.instructions,
        visibility: values.visibility,
        runtime_adapter: 'claude',
        repositories: values.repository ? [values.repository] : [],
        behaviors: {
            ...DEFAULT_LOOP_BEHAVIORS,
            ...behaviors,
            create_prs: values.createPullRequests,
            ...(keepAutoFix
                ? {}
                : { watch_ci: values.autoFixPullRequests, fix_review_comments: values.autoFixPullRequests }),
        },
        triggers: triggersWrite(values),
    }
}

/**
 * Only the fields that changed. On a team loop, instructions, repositories, behaviors and triggers are
 * owner-only, so sending them unchanged would block other members from renaming the loop.
 */
export function loopPatch(loop: LoopDTOApi, values: LoopFormValues): PatchedLoopWriteApi {
    const before = formValuesToLoopWrite(loopToFormValues(loop), loop.behaviors)
    const after = formValuesToLoopWrite(values, loop.behaviors)
    const patch: PatchedLoopWriteApi = {}
    for (const key of Object.keys(after) as (keyof LoopWriteApi)[]) {
        if (key !== 'runtime_adapter' && JSON.stringify(before[key]) !== JSON.stringify(after[key])) {
            Object.assign(patch, { [key]: after[key] })
        }
    }
    return patch
}

export function loopFormError(values: LoopFormValues): string | null {
    if (!values.name.trim()) {
        return 'Enter a name'
    }
    if (!values.instructions.trim()) {
        return 'Enter the instructions the agent follows on each run'
    }
    return null
}

const TIME_FORMAT = new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' })

function formatTime(time: string): string {
    const [hour, minute] = time.split(':').map(Number)
    return TIME_FORMAT.format(new Date(2000, 0, 1, hour || 0, minute || 0))
}

export function describeSchedule(schedule: LoopSchedule): string {
    switch (schedule.frequency) {
        case 'hourly':
            return 'Every hour'
        case 'daily':
            return `Daily at ${formatTime(schedule.time)}`
        case 'weekdays':
            return `Weekdays at ${formatTime(schedule.time)}`
        case 'weekly':
            return `${WEEKDAY_NAMES[schedule.weekday]}s at ${formatTime(schedule.time)}`
    }
}

export function describeTrigger(trigger: LoopTriggerDTOApi): string {
    if (trigger.type === 'schedule') {
        const config = scheduleConfig(trigger)
        if (config.run_at) {
            return `Once on ${new Date(config.run_at).toLocaleString()}`
        }
        const schedule = parseCronSchedule(config.cron_expression)
        return schedule ? describeSchedule(schedule) : `Custom schedule (${config.cron_expression ?? 'not set'})`
    }
    if (trigger.type === 'github') {
        const config = trigger.config as { repository?: string; events?: string[] }
        return `GitHub ${(config.events ?? []).join(', ') || 'events'} in ${config.repository || 'a repository'}`
    }
    return 'API call'
}

const PAUSED_DESCRIPTIONS: Record<string, string> = {
    usage_limited:
        'Paused automatically because your organization reached its usage limit. Upgrade or wait for the limit to reset, then resume the loop.',
    repeated_failures:
        'Paused automatically after too many failed runs in a row. Check the error of the last run, then resume the loop.',
    owner_deactivated: 'Paused because the account of its owner was deactivated.',
    owner_removed_from_org: 'Paused because its owner left the organization.',
    github_integration_disconnected: 'Paused because its GitHub connection was removed.',
}

export function loopPausedDescription(loop: LoopDTOApi): string | null {
    if (loop.enabled || !loop.disabled_reason) {
        return null
    }
    return PAUSED_DESCRIPTIONS[loop.disabled_reason] ?? 'Paused automatically.'
}

const FIRE_BLOCKED_MESSAGES: Record<string, string> = {
    deduped: 'An identical run already started.',
    overlap_skipped: 'The previous run is still in progress.',
    rate_capped: 'This loop reached its daily run limit.',
    team_rate_capped: 'Your project reached its daily loop run limit.',
    disabled: 'This loop is paused. Resume it to start a run.',
    gate_blocked: 'Your organization reached its usage limit.',
    owner_inactive: 'The owner of this loop can no longer start runs.',
    owner_changed: 'The owner of this loop changed while the run started. Try again.',
}

export function loopRunBlockedMessage(reason: string): string {
    return FIRE_BLOCKED_MESSAGES[reason] ?? 'The run didn’t start. Try again.'
}
