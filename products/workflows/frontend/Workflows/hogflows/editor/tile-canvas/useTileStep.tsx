import { useValues } from 'kea'
import { useMemo } from 'react'

import { IconChat, IconPerson, IconSearch, IconSparkles } from '@posthog/icons'

import { IconSlack } from 'lib/lemon-ui/icons'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { workflowLogic } from '../../../workflowLogic'
import { useHogFlowStep } from '../../steps/HogFlowSteps'
import { isFunctionAction } from '../../steps/types'
import type { HogFlow, HogFlowAction } from '../../types'
import { customStepName, stepKindName } from '../../workflowStepCatalog'
import { StepFacts, stepView } from './stepFacts'
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
    invalid: boolean
    shape: TileShape
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

export function useTileStep(action: HogFlowAction, workflow: HogFlow): TileStep {
    const step = useHogFlowStep(action)
    const { hogFunctionTemplatesById, actionValidationErrorsById } = useValues(workflowLogic)
    const { isDarkModeOn } = useValues(themeLogic)

    return useMemo(() => {
        const templateId = isFunctionAction(action) ? action.config.template_id : undefined
        const triggerTemplateId =
            action.type === 'trigger' && 'template_id' in action.config ? action.config.template_id : undefined
        const templateName = hogFunctionTemplatesById[templateId ?? triggerTemplateId ?? '']?.name
        const look = templateId ? TEMPLATE_LOOKS[templateId] : undefined
        const view = stepView(workflow, action, templateName)
        return {
            label: ENDPOINT_LABELS[action.type] ?? stepKindName(action) ?? templateName ?? 'Step',
            customName: customStepName(action, [templateName, view.facts.headline]),
            icon: look?.icon ?? step?.icon,
            color: look?.color?.[isDarkModeOn ? 1 : 0] ?? readableStepColor(step?.color, isDarkModeOn),
            badge: view.badge,
            facts: view.facts,
            presentation: view.presentation,
            invalid: actionValidationErrorsById[action.id]?.valid === false,
            shape: action.type === 'trigger' ? 'start' : action.type === 'exit' ? 'end' : 'step',
        }
    }, [action, workflow, step, hogFunctionTemplatesById, actionValidationErrorsById, isDarkModeOn])
}
