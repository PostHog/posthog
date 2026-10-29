import { IconChat, IconPerson, IconSearch, IconSparkles } from '@posthog/icons'

import { IconSlack } from 'lib/lemon-ui/icons'

import { stepLook, type StepLookTemplates } from '../../steps/stepLook'
import { isFunctionAction } from '../../steps/types'
import type { HogFlowAction } from '../../types'
import { StepFacts, type StepGraph, stepView } from './stepFacts'
import type { StepPresentation } from './stepPresentation'

export type TileShape = 'start' | 'end' | 'step'

export interface TileStep {
    label: string
    customName?: string
    icon: React.ReactNode
    color: string
    badge?: string
    facts: StepFacts
    presentation: StepPresentation
    shape: TileShape
}

export interface TileStepContext {
    templatesById: StepLookTemplates
    isDarkModeOn: boolean
    kindName: string | undefined
}

interface TemplateLook {
    icon?: JSX.Element
    color?: [light: string, dark: string]
}

const AI_COLOR: [string, string] = ['#7c3aed', '#a78bfa']
const TICKET_COLOR: [string, string] = ['#0e7490', '#22d3ee']

const TEMPLATE_LOOKS: Record<string, TemplateLook> = {
    'template-slack': { icon: <IconSlack />, color: ['#611f69', '#e8a6e0'] },
    'template-posthog-create-task': { icon: <IconSparkles />, color: AI_COLOR },
    'template-posthog-run-scout': { icon: <IconSearch />, color: AI_COLOR },
    'template-posthog-send-ticket-message': { icon: <IconChat />, color: TICKET_COLOR },
    'template-posthog-update-ticket': { icon: <IconChat />, color: TICKET_COLOR },
    'template-posthog-update-person-properties': { icon: <IconPerson />, color: ['#475569', '#94a3b8'] },
}

/** The start and end of a workflow are not steps anyone adds, so the step picker has no name for them. */
const ENDPOINT_LABELS: Partial<Record<HogFlowAction['type'], string>> = {
    trigger: 'Trigger',
    exit: 'End',
}

/** Some step colors are dark in both themes, so dark mode lifts them to stay readable on a dark tile. */
function readableStepColor(color: string | undefined, isDarkModeOn: boolean): string {
    if (!color) {
        return 'var(--color-text-secondary)'
    }
    return isDarkModeOn ? `color-mix(in srgb, ${color} 65%, white)` : color
}

/** The step's own name, unless it is still the name the step picker gave it or reads the same as a text shown beside it. */
function customStepName(
    action: HogFlowAction,
    kindName: string | undefined,
    shownElsewhere: (string | undefined)[]
): string | undefined {
    const name = action.name?.trim()
    return name && name !== kindName && !shownElsewhere.includes(name) ? name : undefined
}

export function tileStep(
    action: HogFlowAction,
    workflow: StepGraph,
    { templatesById, isDarkModeOn, kindName }: TileStepContext
): TileStep {
    const look = stepLook(action, templatesById, isDarkModeOn)
    const templateId = isFunctionAction(action) ? action.config.template_id : undefined
    const triggerTemplateId =
        action.type === 'trigger' && 'template_id' in action.config ? action.config.template_id : undefined
    const templateName = templatesById[templateId ?? triggerTemplateId ?? '']?.name
    const templateLook = templateId ? TEMPLATE_LOOKS[templateId] : undefined
    const view = stepView(workflow, action, templateName)
    return {
        label: ENDPOINT_LABELS[action.type] ?? kindName ?? templateName ?? 'Step',
        customName: customStepName(action, kindName, [templateName, view.facts.headline]),
        icon: templateLook?.icon ?? look?.icon,
        color: templateLook?.color?.[isDarkModeOn ? 1 : 0] ?? readableStepColor(look?.color, isDarkModeOn),
        badge: view.badge,
        facts: view.facts,
        presentation: view.presentation,
        shape: action.type === 'trigger' ? 'start' : action.type === 'exit' ? 'end' : 'step',
    }
}
