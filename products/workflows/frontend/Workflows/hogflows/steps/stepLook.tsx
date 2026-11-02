import {
    IconBolt,
    IconClock,
    IconDay,
    IconDecisionTree,
    IconEye,
    IconHourglass,
    IconLeave,
    IconLetter,
    IconNotification,
    IconPercentage,
    IconWebhooks,
} from '@posthog/icons'

import { IconTwilio } from 'lib/lemon-ui/icons'

import type { HogFunctionTemplateType } from '~/types'

import type { HogFlowAction } from '../types'

export type StepLookTemplates = Record<string, Pick<HogFunctionTemplateType, 'icon_url' | 'name'>>

export interface StepLook {
    icon: JSX.Element
    color: string
}

type ThemedColor = string | [light: string, dark: string]

interface FixedLook {
    icon: JSX.Element
    color: ThemedColor
}

const TEMPLATE_ICONS: Record<string, JSX.Element> = {
    'template-email': <IconLetter />,
    'template-webhook': <IconWebhooks />,
    'template-native-push': <IconNotification />,
    'template-posthog-replay-vision': <IconEye />,
}

const DESTINATION_COLORS: Record<string, ThemedColor> = {
    'template-email': '#2F80FA',
    'template-webhook': ['#6500ae', '#B52AD9'],
}

const DESTINATION_COLOR: ThemedColor = ['#F44D01', '#F8BE2A']

const FIXED_LOOKS: Partial<Record<HogFlowAction['type'], FixedLook>> = {
    conditional_branch: { icon: <IconDecisionTree />, color: ['#005841', '#35C46F'] },
    delay: { icon: <IconClock />, color: '#a20031' },
    exit: { icon: <IconLeave />, color: '#4b4b4b' },
    random_cohort_branch: { icon: <IconPercentage />, color: ['#9a004d', '#D6247B'] },
    trigger: { icon: <IconBolt />, color: ['#005841', '#35C46F'] },
    wait_until_condition: { icon: <IconHourglass />, color: '#ffaa00' },
    wait_until_time_window: { icon: <IconDay />, color: '#FF653F' },
    function_email: { icon: <IconLetter />, color: '#2F80FA' },
    function_sms: { icon: <IconTwilio />, color: '#f22f46' },
    function_push: { icon: <IconNotification />, color: DESTINATION_COLOR },
}

function themed(color: ThemedColor, isDarkModeOn: boolean): string {
    return typeof color === 'string' ? color : color[isDarkModeOn ? 1 : 0]
}

function destinationIcon(templateId: string, templatesById: StepLookTemplates): JSX.Element {
    const template = templatesById[templateId]
    return (
        TEMPLATE_ICONS[templateId] ??
        (template?.icon_url ? (
            <img className="LemonIcon !object-contain" src={template.icon_url} alt={template.name} />
        ) : (
            <IconBolt />
        ))
    )
}

export function stepLook(
    action: HogFlowAction,
    templatesById: StepLookTemplates,
    isDarkModeOn: boolean
): StepLook | undefined {
    if (action.type === 'function') {
        const templateId = action.config.template_id
        return {
            icon: destinationIcon(templateId, templatesById),
            color: themed(DESTINATION_COLORS[templateId] ?? DESTINATION_COLOR, isDarkModeOn),
        }
    }
    const look = FIXED_LOOKS[action.type]
    return look && { icon: look.icon, color: themed(look.color, isDarkModeOn) }
}
