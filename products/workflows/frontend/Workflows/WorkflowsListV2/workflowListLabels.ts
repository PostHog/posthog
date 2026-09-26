import { WORKFLOW_TRIGGER_TYPE_OPTIONS } from '../workflowsLogic'
import { WORKFLOW_STATUS_CONFIG } from '../workflowStatus'
import type { WorkflowHealth } from './workflowListRows'

export const STATUS_LABELS: Record<string, string> = Object.fromEntries(
    Object.entries(WORKFLOW_STATUS_CONFIG).map(([status, { label }]) => [status, label])
)

/** The workflow types this list covers. Broadcasts have their own page. */
export const TYPE_LABELS = { messaging: 'Messaging', automation: 'Automation', loop: 'Loop' } as const
export const LIST_TYPES = Object.keys(TYPE_LABELS) as (keyof typeof TYPE_LABELS)[]

export const KIND_LABELS: Record<string, string> = { workflow: 'Workflow', 'email-template': 'Email template' }

export const CHANNEL_LABELS: Record<string, string> = {
    email: 'Email',
    sms: 'SMS',
    push: 'Push',
    slack: 'Slack',
    webhook: 'Webhook',
}

export const TRIGGER_LABELS: Record<string, string> = Object.fromEntries(
    WORKFLOW_TRIGGER_TYPE_OPTIONS.filter((option) => option.value !== 'all').map((option) => [
        option.value,
        option.label,
    ])
)

export const HEALTH_TAGS: Record<WorkflowHealth, { label: string; type: 'danger' | 'success' | 'muted' }> = {
    failing: { label: 'Failing', type: 'danger' },
    healthy: { label: 'Healthy', type: 'success' },
    idle: { label: 'No runs', type: 'muted' },
}

export const OPTIONAL_COLUMN_TITLES = {
    type: 'Type',
    trigger: 'Trigger',
    owner: 'Owner',
    created_by: 'Created by',
    last_7_days: 'Last 7 days',
    health: 'Health',
} as const

export type OptionalColumn = keyof typeof OPTIONAL_COLUMN_TITLES
export const OPTIONAL_COLUMNS = Object.keys(OPTIONAL_COLUMN_TITLES) as OptionalColumn[]
