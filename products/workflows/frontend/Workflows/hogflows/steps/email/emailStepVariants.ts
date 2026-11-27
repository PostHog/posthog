import type { IntegrationType } from '~/types'

import {
    type EmailSenderCandidate,
    isDeliverableEmailSender,
    isVerifiedEmailSender,
} from '../../../../Channels/defaultEmailSender'
import type { HogFlow, HogFlowAction } from '../../types'
import { type TeamUtmDefaults, matchesTeamUtmDefaults } from '../components/utmDefaults'

export type OwnEmailAction = Extract<HogFlowAction, { type: 'function_email' }>
export type SandboxEmailAction = Extract<HogFlowAction, { type: 'email_sandbox' }>
export type EmailStepAction = OwnEmailAction | SandboxEmailAction

export type OwnOnlySetting =
    | 'sender_override'
    | 'several_senders'
    | 'reply_to'
    | 'cc_bcc'
    | 'tracking_off'
    | 'click_tracking_off'
    | 'utm_tags'
    | 'run_link_tag_off'

type EmailValue = Record<string, any>
type Templating = 'hog' | 'liquid'

const CONTENT_KEYS = ['subject', 'preheader', 'text', 'html', 'design'] as const
const SANDBOX_STEP_ID = /^[A-Za-z0-9_-]{1,128}$/

export function isEmailStep(action: HogFlowAction | null | undefined): action is EmailStepAction {
    return action?.type === 'function_email' || action?.type === 'email_sandbox'
}

export function needsSandboxSender(
    action: HogFlowAction,
    canAdoptSandbox: boolean,
    teamUtmDefaults: TeamUtmDefaults
): action is OwnEmailAction {
    return (
        canAdoptSandbox &&
        action.type === 'function_email' &&
        sandboxCanTake(action) &&
        !action.config.inputs?.email?.value?.from?.integrationId &&
        ownOnlySettings(action).every(
            (setting) =>
                setting === 'utm_tags' &&
                teamUtmDefaults.enabled &&
                matchesTeamUtmDefaults(action.config.utm_params ?? {}, teamUtmDefaults)
        )
    )
}

/** A sensitive step stays on an own sender: the sandbox step has no `sensitive` setting, so its email would be stored. */
export function sandboxCanTake(action: HogFlowAction): boolean {
    return SANDBOX_STEP_ID.test(action.id) && !(action.type === 'function_email' && action.config.sensitive)
}

export function sandboxSenderAllowed(workflow: Pick<HogFlow, 'origin_product'>, editingTemplate: boolean): boolean {
    return !editingTemplate && !workflow.origin_product
}

export function hasOwnSender(integrations: EmailSenderCandidate[] | null | undefined): boolean | null {
    return integrations ? integrations.some(isVerifiedEmailSender) : null
}

export function hasDeliverableSender(integrations: IntegrationType[] | null | undefined): boolean | null {
    return integrations ? integrations.some(isDeliverableEmailSender) : null
}

export function sandboxRecipient(action: SandboxEmailAction): string {
    return action.config.inputs.email.value.to?.email ?? ''
}

export function withSandboxRecipient(workflow: HogFlow, actionId: string | null, email: string | undefined): HogFlow {
    const tested = workflow.actions?.find((action) => action.id === actionId)
    if (!email || tested?.type !== 'email_sandbox') {
        return workflow
    }
    const withRecipient = withSandboxEmail(tested, { to: { ...tested.config.inputs.email.value.to, email } })
    return { ...workflow, actions: workflow.actions.map((action) => (action === tested ? withRecipient : action)) }
}

export function toSandboxAction(action: OwnEmailAction): SandboxEmailAction {
    const { type: _type, config, ...graphFields } = action
    const email = config.inputs?.email ?? {}
    return {
        ...graphFields,
        type: 'email_sandbox',
        config: {
            ...categoryOf(config),
            inputs: { email: { templating: templatingOf(email), value: contentOf(email.value ?? {}) } },
        },
    } as SandboxEmailAction
}

export function toOwnEmailAction(action: SandboxEmailAction, integrationId: number): OwnEmailAction {
    const { type: _type, config, ...graphFields } = action
    const email = config.inputs.email
    return {
        ...graphFields,
        type: 'function_email',
        config: {
            template_id: 'template-email',
            ...categoryOf(config),
            inputs: {
                email: {
                    templating: templatingOf(email),
                    value: { ...contentOf(email.value), from: { integrationId } },
                },
            },
        },
    } as OwnEmailAction
}

export function withSandboxEmail(action: SandboxEmailAction, edit: EmailValue): SandboxEmailAction {
    const email = action.config.inputs.email
    const to = edit.to && typeof edit.to === 'object' ? edit.to : email.value.to
    return {
        ...action,
        config: {
            ...action.config,
            inputs: { email: { ...email, value: contentOf({ ...email.value, ...edit, to }) } },
        },
    } as SandboxEmailAction
}

export function ownOnlySettings(action: OwnEmailAction): OwnOnlySetting[] {
    const value: EmailValue = action.config.inputs?.email?.value ?? {}
    const from: EmailValue = value.from ?? {}
    const held: [OwnOnlySetting, boolean][] = [
        ['sender_override', !!(from.email || from.name)],
        ['several_senders', (from.integrationIds?.length ?? 0) > 1],
        ['reply_to', !!value.replyTo],
        ['cc_bcc', !!(value.cc || value.bcc)],
        ['tracking_off', action.config.tracking_enabled === false],
        ['click_tracking_off', action.config.click_tracking_enabled === false],
        ['utm_tags', !!action.config.utm_tags_enabled],
        ['run_link_tag_off', action.config.run_link_tag_enabled === false],
    ]
    return held.filter(([, isHeld]) => isHeld).map(([setting]) => setting)
}

function categoryOf(config: EmailValue): EmailValue {
    return {
        ...(config.message_category_id ? { message_category_id: config.message_category_id } : {}),
        ...(config.message_category_type ? { message_category_type: config.message_category_type } : {}),
    }
}

// A saved email input without templating runs as Hog, so the step it turns into keeps Hog.
function templatingOf(email: EmailValue): Templating {
    return email.templating === 'liquid' ? 'liquid' : 'hog'
}

function contentOf(value: EmailValue): EmailValue {
    const to: EmailValue = value.to ?? {}
    const content: EmailValue = {
        to: { email: typeof to.email === 'string' ? to.email : '', ...(to.name ? { name: to.name } : {}) },
    }
    for (const key of CONTENT_KEYS) {
        if (value[key] !== undefined && value[key] !== null) {
            content[key] = value[key]
        }
    }
    return content
}
