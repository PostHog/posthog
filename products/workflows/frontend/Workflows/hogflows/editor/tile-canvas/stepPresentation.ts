import { parseDelayExpression, parseDelayOffset } from '../../steps/stepDelayLogic'
import type { HogFlowAction, HogFlowEdge } from '../../types'
import {
    ActionOf,
    asRecord,
    asText,
    asTextList,
    conditionText,
    EmailContent,
    emailContent,
    humanKey,
    inputValue,
    outputKeys,
    propertyValueText,
    templateIdOf,
} from './stepValues'

export interface TimeSpan {
    start: number
    end: number
}

export type WaitPresentation =
    | { kind: 'duration'; duration?: string }
    | { kind: 'date'; date?: string; offset?: { duration: string; direction: 'before' | 'after' }; timezone: string }
    | { kind: 'condition'; name?: string; condition: string; maxWait: string }

export interface TimeWindowPresentation {
    day: string
    time: string
    hours?: [start: string, end: string]
    timezone: string
    spans: TimeSpan[][]
}

export interface BranchPath {
    name: string
    rule: string
    edge: Pick<HogFlowEdge, 'type' | 'index'>
    share?: number
}

export type StepPresentation =
    | { kind: 'email'; email: EmailContent }
    | { kind: 'slack'; channel: string; text: string }
    | { kind: 'webhook'; method: string; url?: string; body: Record<string, unknown> }
    | { kind: 'ai-task'; title?: string; prompt?: string; repository?: string; tools: string[]; writes: string[] }
    | { kind: 'scout'; scout?: string; writes: string[] }
    | { kind: 'ticket-message'; message?: string; isNote: boolean }
    | { kind: 'ticket-update'; status?: string; priority?: string; tags: string[] }
    | { kind: 'person'; properties: [key: string, value: string][] }
    | { kind: 'branch'; split: 'condition' | 'random'; key?: string; paths: BranchPath[] }
    | { kind: 'wait'; wait: WaitPresentation }
    | { kind: 'window'; window: TimeWindowPresentation }
    | { kind: 'fields' }

export type StepPresentationKind = StepPresentation['kind']

type BranchCondition = ActionOf<'conditional_branch'>['config']['conditions'][number]
type BranchCohort = ActionOf<'random_cohort_branch'>['config']['cohorts'][number]

/** A draft split can be saved before its paths are set up, so its list can be missing. */
function branchConditions(action: ActionOf<'conditional_branch'>): BranchCondition[] {
    return action.config.conditions ?? []
}

function branchCohorts(action: ActionOf<'random_cohort_branch'>): BranchCohort[] {
    return action.config.cohorts ?? []
}

function splitKey(conditions: BranchCondition[]): string | undefined {
    const keys = new Set(
        conditions.flatMap((condition) =>
            (condition.filters?.properties ?? []).flatMap((filter) => asText(asRecord(filter).key) ?? [])
        )
    )
    return keys.size === 1 ? humanKey([...keys][0]) : undefined
}

const branchEdge = (index: number): BranchPath['edge'] => ({ type: 'branch', index })

function conditionalSplit(action: ActionOf<'conditional_branch'>): StepPresentation {
    const conditions = branchConditions(action)
    return {
        kind: 'branch',
        split: 'condition',
        key: splitKey(conditions),
        paths: [
            ...conditions.map((condition, index) => ({
                name: condition.name || `Condition ${index + 1}`,
                rule: conditionText(condition.filters),
                edge: branchEdge(index),
            })),
            { name: 'No match', rule: 'Everyone else', edge: { type: 'continue' } },
        ],
    }
}

/** The runner picks a group by its weight against the sum of all weights, so the weights read as shares of 100. */
function randomSplit(action: ActionOf<'random_cohort_branch'>): StepPresentation {
    const cohorts = branchCohorts(action)
    const total = cohorts.reduce((sum, cohort) => sum + (cohort.percentage || 0), 0)
    return {
        kind: 'branch',
        split: 'random',
        paths: cohorts.map((cohort, index) => {
            const share = total ? Math.round(((cohort.percentage || 0) / total) * 100) : 0
            return {
                name: cohort.name || `Group ${index + 1}`,
                rule: `${share}% of people`,
                edge: branchEdge(index),
                share,
            }
        }),
    }
}

function timezoneText(config: { use_person_timezone?: boolean; timezone?: string | null }): string {
    return config.use_person_timezone ? "the person's time zone" : (config.timezone ?? 'UTC')
}

function delayUntilDate(until: NonNullable<ActionOf<'delay'>['config']['delay_until']>): WaitPresentation {
    const expression = until.expression.trim()
    const offset = parseDelayOffset(until.offset)
    return {
        kind: 'date',
        date: expression ? humanKey(parseDelayExpression(expression)?.key ?? expression) : undefined,
        offset: offset.direction === 'on' ? undefined : { duration: offset.duration, direction: offset.direction },
        timezone: timezoneText(until),
    }
}

function delayWait(action: ActionOf<'delay'>): WaitPresentation {
    return action.config.delay_until
        ? delayUntilDate(action.config.delay_until)
        : { kind: 'duration', duration: action.config.delay_duration || undefined }
}

export const waitConditionName = (action: ActionOf<'wait_until_condition'>): string | undefined =>
    action.config.condition.name?.trim() || undefined

function waitConditionText(action: ActionOf<'wait_until_condition'>): string {
    const parts = [...(action.config.events ?? []).map((event) => event.filters), action.config.condition.filters]
        .map(conditionText)
        .filter((text) => text !== 'everyone')
    return parts.length ? parts.join(' or ') : 'everyone'
}

function conditionWait(action: ActionOf<'wait_until_condition'>): WaitPresentation {
    return {
        kind: 'condition',
        name: waitConditionName(action),
        condition: waitConditionText(action),
        maxWait: action.config.max_wait_duration,
    }
}

type TimeWindowConfig = ActionOf<'wait_until_time_window'>['config']

const WEEKDAY_NAMES = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']

function isWindowDay(day: TimeWindowConfig['day'], weekday: number): boolean {
    return (
        day === 'any' ||
        (day === 'weekday' && weekday < 5) ||
        (day === 'weekend' && weekday >= 5) ||
        (Array.isArray(day) && (day as string[]).includes(WEEKDAY_NAMES[weekday]))
    )
}

function hoursOf(time: string): number {
    const [hours, minutes] = time.split(':').map(Number)
    return hours + (minutes || 0) / 60
}

/** The open hours of each weekday, Monday first. Matches the workflow runner: a window whose end is not after
 * its start runs past midnight, and that morning part belongs to the day the window started. */
export function timeWindowSpans(config: TimeWindowConfig): TimeSpan[][] {
    return WEEKDAY_NAMES.map((_, weekday) => {
        const isOpenOn = (offset: number): boolean => isWindowDay(config.day, (weekday + 7 - offset) % 7)
        if (config.time === 'any') {
            return isOpenOn(0) ? [{ start: 0, end: 24 }] : []
        }
        const start = hoursOf(config.time[0])
        const end = hoursOf(config.time[1])
        if (end > start) {
            return isOpenOn(0) ? [{ start, end }] : []
        }
        return [...(isOpenOn(1) && end > 0 ? [{ start: 0, end }] : []), ...(isOpenOn(0) ? [{ start, end: 24 }] : [])]
    })
}

function windowDayText(day: TimeWindowConfig['day']): string {
    if (Array.isArray(day)) {
        return day.map((name) => name.charAt(0).toUpperCase() + name.slice(1, 3)).join(', ')
    }
    return day === 'any' ? 'day' : day
}

function timeWindow(config: TimeWindowConfig): TimeWindowPresentation {
    return {
        day: windowDayText(config.day),
        time: config.time === 'any' ? 'any time' : `${config.time[0]} to ${config.time[1]}`,
        hours: config.time === 'any' ? undefined : [config.time[0], config.time[1]],
        timezone: timezoneText(config),
        spans: timeWindowSpans(config),
    }
}

function textInput(action: HogFlowAction, key: string): string | undefined {
    return asText(inputValue(action, key))
}

/** Slack stores a picked channel as `<id>|#<name>`; show the name when it is there. */
function slackChannelName(value: unknown): string {
    const channel = asText(value) ?? ''
    return channel.includes('|') ? channel.split('|')[1] : channel || 'a channel'
}

function functionPresentation(action: HogFlowAction): StepPresentation {
    switch (templateIdOf(action)) {
        case 'template-email': {
            const email = emailContent(action)
            return email ? { kind: 'email', email } : { kind: 'fields' }
        }
        case 'template-slack':
            return {
                kind: 'slack',
                channel: slackChannelName(inputValue(action, 'channel')),
                text: textInput(action, 'text') ?? '',
            }
        case 'template-webhook':
            return {
                kind: 'webhook',
                method: textInput(action, 'method') ?? 'POST',
                url: textInput(action, 'url'),
                body: asRecord(inputValue(action, 'body')),
            }
        case 'template-posthog-create-task':
            return {
                kind: 'ai-task',
                title: textInput(action, 'title'),
                prompt: textInput(action, 'prompt'),
                repository: textInput(action, 'repository'),
                tools: [...asTextList(inputValue(action, 'connectors')), ...asTextList(inputValue(action, 'skills'))],
                writes: outputKeys(action),
            }
        case 'template-posthog-run-scout':
            return {
                kind: 'scout',
                scout: textInput(action, 'skill_name')?.replace(/-/g, ' '),
                writes: outputKeys(action),
            }
        case 'template-posthog-send-ticket-message':
            return {
                kind: 'ticket-message',
                message: textInput(action, 'message'),
                isNote: inputValue(action, 'is_private') === true,
            }
        case 'template-posthog-update-ticket':
            return {
                kind: 'ticket-update',
                status: textInput(action, 'status'),
                priority: textInput(action, 'priority'),
                tags: asTextList(inputValue(action, 'tags')),
            }
        case 'template-posthog-update-person-properties':
            return {
                kind: 'person',
                properties: Object.entries(asRecord(inputValue(action, 'set_properties'))).map(([key, value]) => [
                    key,
                    propertyValueText(value),
                ]),
            }
        default:
            return { kind: 'fields' }
    }
}

/** What a step does, read once from its config, so its caption, its facts and its preview tell the same story. */
export function stepPresentation(action: HogFlowAction): StepPresentation {
    switch (action.type) {
        case 'conditional_branch':
            return conditionalSplit(action)
        case 'random_cohort_branch':
            return randomSplit(action)
        case 'delay':
            return { kind: 'wait', wait: delayWait(action) }
        case 'wait_until_condition':
            return { kind: 'wait', wait: conditionWait(action) }
        case 'wait_until_time_window':
            return { kind: 'window', window: timeWindow(action.config) }
        default:
            return functionPresentation(action)
    }
}
