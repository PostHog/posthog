import type { MessageTemplateListRowApi } from 'products/messaging/frontend/generated/api.schemas'
import type { HogFlowListRowApi, UserBasicApi } from 'products/workflows/frontend/generated/api.schemas'

export const FIXTURE_USERS: Record<'ada' | 'lin', UserBasicApi> = {
    ada: {
        id: 1,
        uuid: '0190a1b2-0000-7000-8000-00000000a001',
        first_name: 'Ada',
        email: 'ada@example.com',
        hedgehog_config: null,
    },
    lin: {
        id: 2,
        uuid: '0190a1b2-0000-7000-8000-00000000a002',
        first_name: '',
        email: 'lin.ops@example.com',
        hedgehog_config: null,
    },
}

export function buildWorkflowRow(
    overrides: Partial<HogFlowListRowApi> & Pick<HogFlowListRowApi, 'id'>
): HogFlowListRowApi {
    return {
        name: `Workflow ${overrides.id}`,
        description: '',
        status: 'draft',
        type: 'automation',
        origin_product: null,
        trigger_type: 'event',
        has_draft: false,
        channels: [],
        dispatches: [],
        email_steps: [],
        created_by: FIXTURE_USERS.ada,
        created_at: '2026-08-01T10:00:00Z',
        updated_at: '2026-08-01T10:00:00Z',
        user_access_level: 'editor',
        last_7_days: { succeeded: 0, failed: 0 },
        ...overrides,
    }
}

export function buildTemplateRow(
    overrides: Partial<MessageTemplateListRowApi> & Pick<MessageTemplateListRowApi, 'id'>
): MessageTemplateListRowApi {
    return {
        name: `Template ${overrides.id}`,
        description: '',
        type: 'email',
        subject: '',
        from_addresses: [],
        created_by: FIXTURE_USERS.lin,
        created_at: '2026-08-01T10:00:00Z',
        updated_at: '2026-08-01T10:00:00Z',
        ...overrides,
    }
}

export function emailStep(
    actionId: string,
    subject: string,
    fromAddresses: string[],
    fromName: string | null = null
): HogFlowListRowApi['email_steps'][number] {
    return {
        action_id: actionId,
        name: `Email ${actionId}`,
        subject,
        from_addresses: fromAddresses,
        from_name: fromName,
        from_integration_ids: [],
        template_uuid: null,
    }
}

/** A small invented project: a mix of statuses, channels and senders, plus two email templates. */
export const FIXTURE_WORKFLOWS: HogFlowListRowApi[] = [
    buildWorkflowRow({
        id: 'wf-welcome',
        name: 'Welcome series',
        description: 'Owner: @maya. Greets new sign-ups.',
        status: 'active',
        type: 'messaging',
        channels: ['email'],
        dispatches: [{ action_type: 'function_email', template_id: 'template-email', count: 2 }],
        email_steps: [
            emailStep('email_1', 'Welcome to Example', ['hello@example.com'], 'Example team'),
            emailStep('email_2', 'Your trial ends soon', ['billing@example.com']),
        ],
        updated_at: '2026-09-20T09:00:00Z',
        last_7_days: { succeeded: 40, failed: 0 },
    }),
    buildWorkflowRow({
        id: 'wf-renewal',
        name: 'Renewal reminder',
        status: 'draft',
        type: 'messaging',
        channels: ['email', 'sms'],
        dispatches: [
            { action_type: 'function_email', template_id: 'template-email', count: 1 },
            { action_type: 'function_sms', template_id: 'template-twilio', count: 1 },
        ],
        email_steps: [emailStep('email_1', 'Your plan renews next week', ['billing@example.com'])],
        updated_at: '2026-09-18T09:00:00Z',
        last_7_days: { succeeded: 3, failed: 2 },
    }),
    buildWorkflowRow({
        id: 'wf-sync',
        name: 'Sync accounts to CRM',
        status: 'draft',
        type: 'automation',
        trigger_type: 'schedule',
        channels: ['webhook'],
        dispatches: [{ action_type: 'function', template_id: 'template-webhook', count: 1 }],
        created_by: FIXTURE_USERS.lin,
        updated_at: '2026-09-10T09:00:00Z',
        last_7_days: null,
    }),
    buildWorkflowRow({
        id: 'wf-old-promo',
        name: 'Spring promo',
        status: 'archived',
        type: 'messaging',
        channels: ['email'],
        dispatches: [{ action_type: 'function_email', template_id: 'template-email', count: 1 }],
        email_steps: [emailStep('email_1', 'Spring deals inside', ['promo@example.com'])],
        updated_at: '2026-04-01T09:00:00Z',
    }),
]

export const FIXTURE_TEMPLATES: MessageTemplateListRowApi[] = [
    buildTemplateRow({
        id: 'tpl-receipt',
        name: 'Receipt',
        subject: 'Your receipt from Example',
        from_addresses: ['billing@example.com'],
        updated_at: '2026-09-19T09:00:00Z',
    }),
    buildTemplateRow({
        id: 'tpl-newsletter',
        name: 'Monthly newsletter',
        subject: 'What is new this month',
        updated_at: '2026-06-01T09:00:00Z',
    }),
]

export function paginated<T>(
    results: T[],
    next: string | null = null
): {
    count: number
    next: string | null
    previous: null
    results: T[]
} {
    return { count: results.length, next, previous: null, results }
}
