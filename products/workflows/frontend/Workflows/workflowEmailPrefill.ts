import { MessageDraft, messageDraftEmail } from '../MessageAudience/messageDrafts'
import type { HogFlow, HogFlowAction } from './hogflows/types'
import type { WorkflowTriggerConfig } from './workflowTriggerPrefill'

const EMAIL_ACTION_ID = 'action_function_email_prefilled'
// The same "One time" setting as the trigger's frequency picker, so the editor shows it selected.
const ONCE_PER_PERSON_MASKING = { hash: '{person.id}', ttl: null, threshold: null }

/**
 * A new workflow that opens ready to enable: the trigger, then the email, then exit. An event
 * trigger sends at most once per person, because someone who hits the event again would
 * otherwise get the same email again.
 */
export function prefilledWorkflow(base: HogFlow, trigger: WorkflowTriggerConfig, email: MessageDraft | null): HogFlow {
    const triggerAction = base.actions.find((action) => action.type === 'trigger')
    const exitAction = base.actions.find((action) => action.type === 'exit')
    if (!triggerAction || !exitAction) {
        return base
    }
    const withTrigger = { ...triggerAction, config: trigger } as HogFlowAction
    if (!email) {
        return {
            ...base,
            actions: base.actions.map((action) => (action.type === 'trigger' ? withTrigger : action)),
        }
    }
    const content = messageDraftEmail(email)
    const emailAction = {
        id: EMAIL_ACTION_ID,
        type: 'function_email',
        name: 'Email',
        description: 'Send an email to the user.',
        created_at: 0,
        updated_at: 0,
        config: {
            template_id: 'template-email',
            inputs: {
                email: {
                    templating: 'liquid',
                    value: {
                        to: { email: '{{ person.properties.email }}', name: '' },
                        from: {},
                        replyTo: '',
                        cc: '',
                        bcc: '',
                        ...content,
                    },
                },
            },
        },
    } as HogFlowAction
    return {
        ...base,
        ...(trigger.type === 'event' ? { trigger_masking: ONCE_PER_PERSON_MASKING as HogFlow['trigger_masking'] } : {}),
        actions: [withTrigger, emailAction, exitAction],
        edges: [
            { from: withTrigger.id, to: emailAction.id, type: 'continue' },
            { from: emailAction.id, to: exitAction.id, type: 'continue' },
        ],
    }
}

export function prefilledEmailContent(workflow: HogFlow): { subject: string; html: string; text: string } | null {
    const action = workflow.actions.find((action) => action.id === EMAIL_ACTION_ID)
    const value = (action?.config as Record<string, any> | undefined)?.inputs?.email?.value
    return value ? { subject: value.subject, html: value.html, text: value.text } : null
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
