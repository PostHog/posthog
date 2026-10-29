import { isBranchingAction } from '../../tree/workflowTree'
import type { HogFlow, HogFlowAction } from '../../types'
import { StepPresentation, stepPresentation, TimeWindowPresentation, WaitPresentation } from './stepPresentation'
import {
    ActionOf,
    asRecord,
    conditionText,
    EmailContent,
    eventNames,
    firstLine,
    firstSentence,
    humanDuration,
    humanKey,
    joinList,
    plainVariables,
    templateIdOf,
} from './stepValues'
import { outgoingEdges, pathActions, PathGroup } from './tileCanvasModel'

type Field = [label: string, value: string]

export interface StepFacts {
    headline: string
    detail?: string
    fields: Field[]
}

type PresentationOf<Kind extends StepPresentation['kind']> = Extract<StepPresentation, { kind: Kind }>

const fieldIf = (label: string, value: string | undefined): Field[] => (value ? [[label, value]] : [])

function emailFacts(email: EmailContent, action: HogFlowAction): StepFacts {
    const isTransactional = action.type === 'function_email' && action.config.message_category_type === 'transactional'
    const preheader = email.preheader && plainVariables(email.preheader)
    return {
        headline: plainVariables(email.subject),
        detail: preheader,
        fields: [
            ['Preview', preheader ?? 'None'],
            ['To', email.to],
            ['Type', isTransactional ? 'Transactional' : 'Marketing'],
        ],
    }
}

function slackFacts({ channel, text }: PresentationOf<'slack'>): StepFacts {
    const message = plainVariables(text)
    return {
        headline: `Post to ${channel}`,
        detail: firstLine(message) || undefined,
        fields: [
            ['Channel', channel],
            ['Message', message || 'Not set'],
        ],
    }
}

function webhookFacts({ method, url, body }: PresentationOf<'webhook'>): StepFacts {
    const sends = joinList(Object.keys(body))
    return {
        headline: url ? `Call ${url.replace(/^https?:\/\//, '').split('/')[0]}` : 'Call a URL',
        detail: sends ? `Sends ${sends}` : undefined,
        fields: [['Request', `${method} ${url ?? 'URL not set'}`], ...fieldIf('Sends', sends)],
    }
}

function aiTaskFacts({ title, prompt, repository, writes }: PresentationOf<'ai-task'>): StepFacts {
    const instructions = plainVariables(prompt ?? '')
    return {
        headline: title ? plainVariables(title) : firstSentence(instructions) || 'AI task',
        detail: firstSentence(instructions) || undefined,
        fields: [
            ['Instructions', instructions || 'Not set'],
            ...fieldIf('Repository', repository),
            ...fieldIf('Writes', joinList(writes)),
        ],
    }
}

function scoutFacts({ scout, writes }: PresentationOf<'scout'>): StepFacts {
    const written = joinList(writes)
    return {
        headline: scout ? `Run the ${scout} scout` : 'Run a scout',
        detail: written ? `Writes ${written}` : undefined,
        fields: [['Scout', scout || 'Not set'], ...fieldIf('Writes', written)],
    }
}

const isLoneVariable = (text: string): boolean => /^\{\{?[^}]+\}?\}$/.test(text.trim())

function ticketMessageFacts({ message = '', isNote }: PresentationOf<'ticket-message'>): StepFacts {
    const text = plainVariables(message)
    return {
        headline: isNote ? 'Save a note for an agent' : 'Reply to the customer',
        detail: isLoneVariable(message) ? `Sends the ${text} from earlier` : text || undefined,
        fields: [
            ['Posts', isNote ? 'A private note on the ticket' : 'A reply the customer sees'],
            ['Message', text || 'Not set'],
        ],
    }
}

function ticketUpdateFacts({ status, priority, tags }: PresentationOf<'ticket-update'>): StepFacts {
    const tagList = tags.join(', ')
    const changes = [
        ...(status ? [`Set status to ${status}`] : []),
        ...(priority ? [`Set priority to ${priority}`] : []),
        ...(tagList ? [`Tag ${tagList}`] : []),
    ]
    return {
        headline: changes[0] ?? 'Update the ticket',
        detail: changes.slice(1).join(', ') || undefined,
        fields: [...fieldIf('Status', status), ...fieldIf('Priority', priority), ...fieldIf('Tags', tagList)],
    }
}

function personFacts({ properties }: PresentationOf<'person'>): StepFacts {
    return {
        headline: properties.length
            ? properties.map(([key, value]) => `Set ${humanKey(key)} to ${value}`).join(', ')
            : 'Update person properties',
        detail: 'On the person',
        fields: properties.map(([key, value]) => [humanKey(key), value]),
    }
}

function conditionalSplitFacts({ key, paths }: PresentationOf<'branch'>): StepFacts {
    const conditionNames = paths.filter((path) => path.edge.type === 'branch').map((path) => path.name)
    return {
        headline: key ? `Split by ${key}` : 'Split by condition',
        detail: conditionNames.length ? `${conditionNames.join(', ')}, or no match` : 'No conditions yet',
        fields: paths.map((path) => [path.name, path.rule]),
    }
}

function randomSplitFacts({ paths }: PresentationOf<'branch'>): StepFacts {
    return {
        headline: 'Random split',
        detail: paths.map((path) => `${path.share}%`).join(' / ') || undefined,
        fields: paths.map((path) => [path.name, path.rule]),
    }
}

/** How long a wait lasts or what it waits for, in the words its caption, card and preview all use. */
export function waitText(wait: WaitPresentation): string | undefined {
    switch (wait.kind) {
        case 'duration':
            return wait.duration ? humanDuration(wait.duration) : undefined
        case 'date':
            if (!wait.date) {
                return undefined
            }
            return wait.offset
                ? `${humanDuration(wait.offset.duration)} ${wait.offset.direction} ${wait.date}`
                : wait.date
        case 'condition':
            return humanDuration(wait.maxWait)
    }
}

function waitFacts(wait: WaitPresentation): StepFacts {
    const text = waitText(wait) ?? 'Not set'
    switch (wait.kind) {
        case 'duration':
            return { headline: `Wait ${text}`, detail: 'Then continue', fields: [['Wait', text]] }
        case 'date':
            return {
                headline: wait.date ? `Wait until ${text}` : 'Wait until a date',
                detail: `Then continue (${wait.timezone})`,
                fields: [
                    ['Waits until', text],
                    ['Time zone', wait.timezone],
                ],
            }
        case 'condition':
            return {
                headline: `Wait for ${wait.name ?? 'a condition'}`,
                detail: `Gives up after ${text}`,
                fields: [
                    ['Waits for', wait.condition],
                    ['Gives up', `After ${text}`],
                ],
            }
    }
}

function windowFacts({ day, time, timezone }: TimeWindowPresentation): StepFacts {
    return {
        headline: `Next ${day}, ${time}`,
        detail: `Holds people until then (${timezone})`,
        fields: [
            ['Day', day],
            ['Time', time],
            ['Time zone', timezone],
        ],
    }
}

function otherStepFacts(action: HogFlowAction, templateName: string | undefined): StepFacts {
    const runs = templateName ?? action.name
    // A new step takes the template's name, so any other name is one the author chose.
    const renamed = !!templateName && action.name.trim().toLowerCase() !== templateName.toLowerCase()
    return {
        headline: renamed ? action.name : runs,
        detail: action.description || (renamed ? templateName : undefined),
        fields: [['Runs', runs]],
    }
}

function presentationFacts(
    presentation: StepPresentation,
    action: HogFlowAction,
    templateName: string | undefined
): StepFacts {
    switch (presentation.kind) {
        case 'email':
            return emailFacts(presentation.email, action)
        case 'slack':
            return slackFacts(presentation)
        case 'webhook':
            return webhookFacts(presentation)
        case 'ai-task':
            return aiTaskFacts(presentation)
        case 'scout':
            return scoutFacts(presentation)
        case 'ticket-message':
            return ticketMessageFacts(presentation)
        case 'ticket-update':
            return ticketUpdateFacts(presentation)
        case 'person':
            return personFacts(presentation)
        case 'branch':
            return presentation.split === 'condition'
                ? conditionalSplitFacts(presentation)
                : randomSplitFacts(presentation)
        case 'wait':
            return waitFacts(presentation.wait)
        case 'window':
            return windowFacts(presentation.window)
        case 'fields':
            return otherStepFacts(action, templateName)
    }
}

type TriggerConfig = ActionOf<'trigger'>['config']

function eventTriggerFacts(filters: Extract<TriggerConfig, { type: 'event' }>['filters']): StepFacts {
    // A saved draft can hold no filters at all.
    const { events: triggerEvents, actions, properties: triggerProperties } = asRecord(filters)
    const events = [...eventNames(triggerEvents), ...eventNames(actions)]
    const properties = Array.isArray(triggerProperties) ? triggerProperties : []
    const who = properties.length ? conditionText({ properties }) : 'Anyone'
    return {
        headline: events.join(' or ') || 'Any event',
        detail: properties.length ? `Starts when someone does this, if ${who}` : 'Starts when someone does this',
        fields: [
            ['Starts on', events.join(', ') || 'Any event'],
            ['Who', who],
        ],
    }
}

function audienceTriggerFacts(filters: Extract<TriggerConfig, { type: 'batch' }>['filters']): StepFacts {
    const audience = conditionText({ properties: filters?.properties })
    return {
        headline: audience === 'everyone' ? 'Everyone' : audience.charAt(0).toUpperCase() + audience.slice(1),
        detail: `Audience, starts once for every ${filters?.audience_type === 'accounts' ? 'account' : 'person'}`,
        fields: [['Who', audience]],
    }
}

function triggerFacts(trigger: TriggerConfig, templateName: string | undefined): StepFacts {
    switch (trigger.type) {
        case 'event':
        case 'internal-event':
            return eventTriggerFacts(trigger.filters)
        case 'batch':
            return audienceTriggerFacts(trigger.filters)
        case 'schedule':
            return {
                headline: 'On a schedule',
                detail: 'Runs at the times you set',
                fields: [['Starts', 'On a schedule']],
            }
        case 'manual':
            return {
                headline: 'Run by hand',
                detail: 'Someone starts it',
                fields: [['Starts', 'When someone runs it']],
            }
        case 'webhook':
            return {
                headline: templateName ?? 'Webhook call',
                detail: 'Starts when the webhook is called',
                fields: [['Starts on', templateName ?? 'A webhook call']],
            }
        case 'tracking_pixel':
            return {
                headline: 'Tracking pixel',
                detail: 'Starts when the pixel loads',
                fields: [['Starts on', 'A tracking pixel load']],
            }
        case 'api':
            return {
                headline: 'Transactional email',
                detail: 'Starts each time the send endpoint is called',
                fields: [['Starts on', 'A send API call']],
            }
        case 'cohort': {
            const change = trigger.transition === 'left' ? 'leaves' : 'joins'
            return {
                headline: 'Cohort membership',
                detail: `Starts when a person ${change} the cohort`,
                fields: [['Starts on', `A person ${change} the cohort`]],
            }
        }
        default:
            return {
                headline: trigger.table_name,
                detail: 'Starts for every new row',
                fields: [['Table', trigger.table_name]],
            }
    }
}

const EXIT_RULES: Record<string, string> = {
    exit_on_conversion: 'they convert',
    exit_on_trigger_not_matched: 'they stop matching the trigger',
    exit_on_trigger_not_matched_or_conversion: 'they convert or stop matching the trigger',
}

function exitFacts(workflow: Pick<HogFlow, 'exit_condition'>, action: ActionOf<'exit'>): StepFacts {
    const earlyExit = EXIT_RULES[workflow.exit_condition]
    return {
        headline: action.config.reason || 'End of workflow',
        detail: earlyExit
            ? `People also leave early when ${earlyExit}`
            : 'Nobody leaves early: everyone runs to the end',
        fields: [
            ['Ends when', action.config.reason || 'The path runs out'],
            ['Also ends', earlyExit ? `When ${earlyExit}` : 'Nobody leaves early: everyone runs to the end'],
        ],
    }
}

function factsOf(
    workflow: Pick<HogFlow, 'exit_condition'>,
    action: HogFlowAction,
    presentation: StepPresentation,
    templateName: string | undefined
): StepFacts {
    switch (action.type) {
        case 'trigger':
            return triggerFacts(action.config, templateName)
        case 'exit':
            return exitFacts(workflow, action)
        default:
            return presentationFacts(presentation, action, templateName)
    }
}

const TRIGGER_SOURCES: Record<string, string> = {
    event: 'Event',
    'internal-event': 'Event',
    webhook: 'Webhook',
    manual: 'Manual',
    tracking_pixel: 'Pixel',
    schedule: 'Schedule',
    batch: 'Audience',
    'data-warehouse-table': 'Warehouse',
    'data-warehouse-view': 'Warehouse',
}

const shortTime = (time: string): string => (time.endsWith(':00') ? time.slice(0, -3) : time)

function waitBadge(wait: WaitPresentation): string | undefined {
    switch (wait.kind) {
        case 'duration':
            return wait.duration
        case 'date':
            return 'Date'
        case 'condition':
            return `≤ ${wait.maxWait}`
    }
}

const countText = (count: number, one: string, many: string): string => `${count} ${count === 1 ? one : many}`

function badgeOf(action: HogFlowAction, presentation: StepPresentation, pathCount: number): string | undefined {
    if (action.type === 'trigger') {
        return TRIGGER_SOURCES[action.config.type]
    }
    switch (presentation.kind) {
        case 'wait':
            return waitBadge(presentation.wait)
        case 'window': {
            const hours = presentation.window.hours
            return hours ? `${shortTime(hours[0])}-${shortTime(hours[1])}` : undefined
        }
        case 'branch':
            return `${pathCount} paths`
        case 'webhook':
            return presentation.method
        case 'ai-task':
            return presentation.tools.length ? countText(presentation.tools.length, 'tool', 'tools') : undefined
        default:
            return undefined
    }
}

export interface StepView {
    presentation: StepPresentation
    facts: StepFacts
    badge?: string
}

interface CachedStepView {
    inputs: unknown[]
    view: StepView
}

const stepViews = new WeakMap<HogFlowAction, CachedStepView>()

const sameInputs = (a: unknown[], b: unknown[]): boolean =>
    a.length === b.length && a.every((value, i) => value === b[i])

/**
 * What a tile shows for a step: read once per step object and kept until the step or the few workflow facts it
 * reads change, however many tiles, cards and previews show it.
 */
export function stepView(
    workflow: Pick<HogFlow, 'edges' | 'exit_condition' | 'actions'>,
    action: HogFlowAction,
    templateName?: string
): StepView {
    const pathCount = outgoingEdges(workflow, action.id).length
    const inputs = [pathCount, action.type === 'exit' ? workflow.exit_condition : undefined, templateName]
    const cached = stepViews.get(action)
    if (cached && sameInputs(cached.inputs, inputs)) {
        return cached.view
    }
    const presentation: StepPresentation =
        action.type === 'trigger' || action.type === 'exit' ? { kind: 'fields' } : stepPresentation(action)
    const view = {
        presentation,
        facts: factsOf(workflow, action, presentation, templateName),
        badge: badgeOf(action, presentation, pathCount),
    }
    stepViews.set(action, { inputs, view })
    return view
}

export function stepFacts(workflow: HogFlow, action: HogFlowAction, templateName?: string): StepFacts {
    return stepView(workflow, action, templateName).facts
}

export function stepBadge(
    workflow: Pick<HogFlow, 'edges' | 'exit_condition' | 'actions'>,
    action: HogFlowAction
): string | undefined {
    return stepView(workflow, action).badge
}

const SUMMARY_LENGTH = 3

/** The steps after a split inside the path run on only some of its people, so the summary stops at the split. */
function summarizedSteps(actions: HogFlowAction[]): HogFlowAction[] {
    const split = actions.findIndex(isBranchingAction)
    return actions.slice(0, split === -1 ? SUMMARY_LENGTH : Math.min(split + 1, SUMMARY_LENGTH))
}

export function pathSummary(
    workflow: HogFlow,
    group: PathGroup,
    templateNameOf?: (id: string) => string | undefined
): string {
    return summarizedSteps(pathActions(workflow, group))
        .map((action) => {
            const templateId = templateIdOf(action)
            return stepFacts(workflow, action, templateId ? templateNameOf?.(templateId) : undefined).headline
        })
        .join(', then ')
}
