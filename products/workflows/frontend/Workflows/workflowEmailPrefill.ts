import type { MessageTemplateApi } from 'products/messaging/frontend/generated/api.schemas'

import { EmailBrand, applyEmailBrand } from '../MessageAudience/emailBrand'
import { MessageDraft, messageDraftEmail } from '../MessageAudience/messageDrafts'
import { LIQUID_EXPRESSION } from '../Transactional/wizard/emailVariables'
import type { TeamUtmDefaults } from './hogflows/steps/components/utmDefaults'
import { needsSandboxSender, toSandboxAction } from './hogflows/steps/email/emailStepVariants'
import type { HogFlow, HogFlowAction } from './hogflows/types'
import type { WorkflowTriggerConfig } from './workflowTriggerPrefill'

export const EMAIL_ACTION_ID = 'action_function_email_prefilled'
export const TEMPLATE_EMAIL_ACTION_ID = 'action_function_email_from_template'
// The same "One time" setting as the trigger's frequency picker, so the editor shows it selected.
const ONCE_PER_PERSON_MASKING = { hash: '{person.id}', ttl: null, threshold: null }
const PERSON_RECIPIENT = { email: '{{ person.properties.email }}', name: '' }

/**
 * A new workflow that opens ready to enable: the trigger, then the email, then exit. An event
 * trigger sends at most once per person, because someone who hits the event again would
 * otherwise get the same email again.
 */
export function prefilledWorkflow(base: HogFlow, trigger: WorkflowTriggerConfig, email: MessageDraft | null): HogFlow {
    if (!email) {
        return withTriggerConfigOnly(base, trigger)
    }
    const emailAction = emailStep(EMAIL_ACTION_ID, 'Email', {
        from: {},
        replyTo: '',
        cc: '',
        bcc: '',
        ...messageDraftEmail(email),
    })
    const workflow = withEmailStep(base, trigger, emailAction)
    return trigger.type === 'event'
        ? { ...workflow, trigger_masking: ONCE_PER_PERSON_MASKING as HogFlow['trigger_masking'] }
        : workflow
}

/**
 * A new workflow that sends a transactional template's published email, the way its API sends do:
 * on every trigger, past marketing opt-outs, and as sensitive as the template.
 */
export function templatePrefilledWorkflow(
    base: HogFlow,
    trigger: WorkflowTriggerConfig,
    template: Pick<MessageTemplateApi, 'name' | 'sensitive' | 'content'>
): HogFlow {
    const { from, ...content } = withEventPropertiesForVariables(template.content?.email ?? {})
    const emailAction = emailStep(
        TEMPLATE_EMAIL_ACTION_ID,
        template.name,
        { cc: '', bcc: '', replyTo: '', ...content, from: from ?? {} },
        { message_category_type: 'transactional', sensitive: !!template.sensitive }
    )
    return { ...withEmailStep(base, trigger, emailAction), name: template.name }
}

const API_VARIABLE = /(^|[^\w.])variables\./g

/** An event run gets no send API `variables`, so the copied email reads the same names from the event's properties. */
function withEventPropertiesForVariables<T>(value: T): T {
    if (typeof value === 'string') {
        return value.replace(LIQUID_EXPRESSION, (tag) => tag.replace(API_VARIABLE, '$1event.properties.')) as T
    }
    if (Array.isArray(value)) {
        return value.map(withEventPropertiesForVariables) as T
    }
    if (value && typeof value === 'object') {
        return Object.fromEntries(
            Object.entries(value).map(([key, nested]) => [key, withEventPropertiesForVariables(nested)])
        ) as T
    }
    return value
}

function withTriggerConfigOnly(base: HogFlow, trigger: WorkflowTriggerConfig): HogFlow {
    return {
        ...base,
        actions: base.actions.map((action) =>
            action.type === 'trigger' ? ({ ...action, config: trigger } as HogFlowAction) : action
        ),
    }
}

function emailStep(
    id: string,
    name: string,
    value: Record<string, unknown>,
    stepConfig: Record<string, unknown> = {}
): HogFlowAction {
    return {
        id,
        type: 'function_email',
        name,
        description: 'Send an email to the user.',
        created_at: 0,
        updated_at: 0,
        config: {
            template_id: 'template-email',
            ...stepConfig,
            inputs: { email: { templating: 'liquid', value: { ...value, to: PERSON_RECIPIENT } } },
        },
    } as HogFlowAction
}

function withEmailStep(base: HogFlow, trigger: WorkflowTriggerConfig, emailAction: HogFlowAction): HogFlow {
    const triggerAction = base.actions.find((action) => action.type === 'trigger')
    const exitAction = base.actions.find((action) => action.type === 'exit')
    if (!triggerAction || !exitAction) {
        return base
    }
    const withTrigger = { ...triggerAction, config: trigger } as HogFlowAction
    return {
        ...base,
        actions: [withTrigger, emailAction, exitAction],
        edges: [
            { from: withTrigger.id, to: emailAction.id, type: 'continue' },
            { from: emailAction.id, to: exitAction.id, type: 'continue' },
        ],
    }
}

export function prefilledEmailContent(
    workflow: HogFlow
): { subject: string; preheader: string; html: string; text: string } | null {
    const action = workflow.actions.find((action) => action.id === EMAIL_ACTION_ID)
    const value = (action?.config as Record<string, any> | undefined)?.inputs?.email?.value
    return value
        ? { subject: value.subject, preheader: value.preheader ?? '', html: value.html, text: value.text }
        : null
}

export function withPrefilledEmail(workflow: HogFlow, email: MessageDraft): HogFlow {
    const content = messageDraftEmail(email)
    return {
        ...workflow,
        actions: workflow.actions.map((action) => {
            const config = action.config as Record<string, any>
            if (action.id !== EMAIL_ACTION_ID || !config?.inputs?.email?.value) {
                return action
            }
            return {
                ...action,
                config: {
                    ...config,
                    inputs: {
                        ...config.inputs,
                        email: { ...config.inputs.email, value: { ...config.inputs.email.value, ...content } },
                    },
                },
            } as HogFlowAction
        }),
    }
}

export function withEmailSender(workflow: HogFlow, integrationId: number): { workflow: HogFlow; filled: boolean } {
    let filled = false
    const actions = workflow.actions.map((action) => {
        const config = action.config as Record<string, any>
        const value = config?.template_id === 'template-email' ? config.inputs?.email?.value : null
        if (!value || value.from?.integrationId) {
            return action
        }
        filled = true
        return {
            ...action,
            config: {
                ...config,
                inputs: {
                    ...config.inputs,
                    email: { ...config.inputs.email, value: { ...value, from: { ...value.from, integrationId } } },
                },
            },
        } as HogFlowAction
    })
    return { workflow: filled ? { ...workflow, actions } : workflow, filled }
}

export function withSandboxSender(workflow: HogFlow, teamUtmDefaults: TeamUtmDefaults): HogFlow {
    let switched = false
    const actions = workflow.actions.map((action) => {
        if (!needsSandboxSender(action, true, teamUtmDefaults)) {
            return action
        }
        switched = true
        return toSandboxAction(action)
    })
    return switched ? { ...workflow, actions } : workflow
}

/** The prefilled email step inside the brand's design, or the workflow unchanged when the brand doesn't fit. */
export function withEmailBrand(workflow: HogFlow, brand: EmailBrand | null): HogFlow {
    if (!brand) {
        return workflow
    }
    let branded = false
    const actions = workflow.actions.map((action) => {
        if (action.id !== EMAIL_ACTION_ID) {
            return action
        }
        const config = action.config as Record<string, any>
        const value = config.inputs?.email?.value
        const content = value ? applyEmailBrand(value, brand) : null
        if (!content) {
            return action
        }
        branded = true
        return {
            ...action,
            config: {
                ...config,
                inputs: { ...config.inputs, email: { ...config.inputs.email, value: { ...value, ...content } } },
            },
        } as HogFlowAction
    })
    return branded ? { ...workflow, actions } : workflow
}
