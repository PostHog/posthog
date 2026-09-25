import type { FacetDefinition } from 'lib/components/FacetSearchBar/facetQuery'

import {
    CHANNEL_LABELS,
    HEALTH_TAGS,
    KIND_LABELS,
    STATUS_LABELS,
    TRIGGER_LABELS,
    TYPE_LABELS,
} from './workflowListLabels'
import { WorkflowListRow, rowCreatedBy } from './workflowListRows'

const HEALTH_LABELS: Record<string, string> = Object.fromEntries(
    Object.entries(HEALTH_TAGS).map(([health, { label }]) => [health, label])
)

const labelFrom =
    (labels: Record<string, string>) =>
    (value: string): string =>
        labels[value] ?? value

const unique = (values: string[]): string[] => [...new Set(values)]

function rowSubjects(row: WorkflowListRow): string[] {
    if (row.kind === 'email_template') {
        return row.template.subject ? [row.template.subject] : []
    }
    return unique(row.workflow.email_steps.map((step) => step.subject).filter(Boolean))
}

function rowFromAddresses(row: WorkflowListRow): string[] {
    if (row.kind === 'email_template') {
        return unique([...row.template.from_addresses])
    }
    return unique(row.workflow.email_steps.flatMap((step) => step.from_addresses))
}

/** Every word of the text must appear in the name, description, email step names, subjects or From addresses. */
export function matchesWorkflowListText(row: WorkflowListRow, text: string): boolean {
    const haystack = [
        row.name,
        row.kind === 'workflow' ? row.workflow.description : row.template.description,
        ...(row.kind === 'workflow' ? row.workflow.email_steps.map((step) => step.name) : []),
        ...rowSubjects(row),
        ...rowFromAddresses(row),
    ]
        .join('\n')
        .toLowerCase()
    return text
        .toLowerCase()
        .split(/\s+/)
        .filter(Boolean)
        .every((word) => haystack.includes(word))
}

/** The facets of the workflows list. `rows` supplies the names shown for creator uuids. */
export function buildWorkflowListFacets(rows: WorkflowListRow[]): FacetDefinition<WorkflowListRow>[] {
    const creatorNames = new Map<string, string>()
    for (const row of rows) {
        const user = rowCreatedBy(row)
        if (user) {
            creatorNames.set(user.uuid, user.first_name || user.email)
        }
    }

    return [
        {
            key: 'status',
            label: 'Status',
            description: 'Draft, active or archived',
            showOnFocus: true,
            order: 1,
            getValues: (row) => (row.kind === 'workflow' ? [row.workflow.status] : []),
            formatValue: labelFrom(STATUS_LABELS),
        },
        {
            key: 'kind',
            label: 'Kind',
            description: 'Workflow or email template',
            showOnFocus: true,
            order: 2,
            getValues: (row) => [row.kind === 'workflow' ? 'workflow' : 'email-template'],
            formatValue: labelFrom(KIND_LABELS),
        },
        {
            key: 'channel',
            label: 'Channel',
            description: 'What it sends: email, SMS, push, Slack or webhook',
            showOnFocus: true,
            order: 3,
            getValues: (row) => (row.kind === 'workflow' ? [...row.workflow.channels] : ['email']),
            formatValue: labelFrom(CHANNEL_LABELS),
        },
        {
            key: 'sends',
            aliases: ['subject'],
            label: 'Sends',
            description: 'Email subject',
            showOnFocus: true,
            order: 4,
            getValues: rowSubjects,
        },
        {
            key: 'from',
            label: 'From',
            description: 'Sender address',
            showOnFocus: true,
            order: 5,
            getValues: rowFromAddresses,
        },
        {
            key: 'owner',
            label: 'Owner',
            description: 'Owner: @name in the description, else the creator',
            showOnFocus: true,
            order: 6,
            getValues: (row) => (row.kind === 'workflow' ? row.owners : []),
            formatValue: (value) => `@${value}`,
        },
        {
            key: 'health',
            label: 'Health',
            description: 'Failed runs in the last 7 days',
            showOnFocus: true,
            order: 7,
            getValues: (row) => (row.kind === 'workflow' ? [row.health] : []),
            formatValue: labelFrom(HEALTH_LABELS),
        },
        {
            key: 'type',
            label: 'Type',
            description: 'Messaging, automation or loop',
            order: 8,
            getValues: (row) => (row.kind === 'workflow' ? [row.workflow.type] : []),
            formatValue: labelFrom(TYPE_LABELS),
        },
        {
            key: 'trigger',
            label: 'Trigger',
            description: 'What starts the workflow',
            order: 9,
            getValues: (row) =>
                row.kind === 'workflow' && row.workflow.trigger_type ? [row.workflow.trigger_type] : [],
            formatValue: labelFrom(TRIGGER_LABELS),
        },
        {
            key: 'created-by',
            label: 'Created by',
            description: 'Who created it',
            order: 10,
            getValues: (row) => {
                const user = rowCreatedBy(row)
                return user ? [user.uuid] : []
            },
            formatValue: (value) => creatorNames.get(value) ?? value,
        },
    ]
}
