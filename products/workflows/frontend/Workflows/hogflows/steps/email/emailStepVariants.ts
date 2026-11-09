import type { IntegrationType } from '~/types'

import type { HogFlow, HogFlowAction } from '../../types'

export type OwnEmailAction = Extract<HogFlowAction, { type: 'function_email' }>
export type SandboxEmailAction = Extract<HogFlowAction, { type: 'email_sandbox' }>
export type EmailStepAction = OwnEmailAction | SandboxEmailAction

export type OwnOnlySetting = 'sender_override' | 'several_senders' | 'reply_to' | 'cc_bcc' | 'tracking_off' | 'utm_tags'

type EmailValue = Record<string, any>
type Templating = 'hog' | 'liquid'

const CONTENT_KEYS = ['subject', 'preheader', 'text', 'html', 'design'] as const

export function isEmailStep(action: HogFlowAction | null | undefined): action is EmailStepAction {
    return action?.type === 'function_email' || action?.type === 'email_sandbox'
}

/** An own email step with no sender yet, which a project that can use the sandbox sender sends from it instead. */
export function needsSandboxSender(action: HogFlowAction, canAdoptSandbox: boolean): action is OwnEmailAction {
    return (
        canAdoptSandbox && action.type === 'function_email' && !action.config.inputs?.email?.value?.from?.integrationId
    )
}

/** The server refuses a sandbox step in a template or in a workflow another product owns. */
export function sandboxSenderAllowed(workflow: Pick<HogFlow, 'origin_product'>, editingTemplate: boolean): boolean {
    return !editingTemplate && !workflow.origin_product
}

/** Null while the senders are still loading, so a caller can't mistake "not loaded" for "has none". */
export function hasOwnSender(integrations: IntegrationType[] | null | undefined): boolean | null {
    return integrations
        ? integrations.some((integration) => integration.kind === 'email' && integration.config?.verified === true)
        : null
}

/** The API saves a sandbox draft without a To, so a missing recipient reads as empty. */
export function sandboxRecipient(action: SandboxEmailAction): string {
    return action.config.inputs.email.value.to?.email ?? ''
}

/** The step's own To can be a literal address, so changing only the test person's email would still send to it. */
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

/**
 * The sandbox step with an edit to its email applied, keeping only the fields a sandbox step stores.
 * The content editor hands back its own string `to`, which must not replace the step's recipient.
 */
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
    const settings: OwnOnlySetting[] = []
    if (from.email || from.name) {
        settings.push('sender_override')
    }
    if ((from.integrationIds?.length ?? 0) > 1) {
        settings.push('several_senders')
    }
    if (value.replyTo) {
        settings.push('reply_to')
    }
    if (value.cc || value.bcc) {
        settings.push('cc_bcc')
    }
    // Switching back to an own sender starts tracked and untagged, so these are lost too.
    if (action.config.tracking_enabled === false) {
        settings.push('tracking_off')
    }
    if (action.config.utm_tags_enabled) {
        settings.push('utm_tags')
    }
    return settings
}

function categoryOf(config: EmailValue): EmailValue {
    return {
        ...(config.message_category_id ? { message_category_id: config.message_category_id } : {}),
        ...(config.message_category_type ? { message_category_type: config.message_category_type } : {}),
    }
}

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
