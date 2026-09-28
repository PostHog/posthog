import type { FacetDefinition } from './FacetSearchBar/facetQuery'
import { HEALTH_TAGS, STATUS_LABELS, TRIGGER_LABELS, TYPE_LABELS } from './workflowListLabels'
import { WorkflowListRow } from './workflowListRows'

const HEALTH_LABELS: Record<string, string> = Object.fromEntries(
    Object.entries(HEALTH_TAGS).map(([health, { label }]) => [health, label])
)

const labelFrom =
    (labels: Record<string, string>) =>
    (value: string): string =>
        labels[value] ?? value

/** Every word of the text must appear in the name or description. */
export function matchesWorkflowListText(row: WorkflowListRow, text: string): boolean {
    return text
        .toLowerCase()
        .split(/\s+/)
        .filter(Boolean)
        .every((word) => row.searchText.includes(word))
}

/** `rows` supplies the names shown for creator uuids. */
export function buildWorkflowListFacets(rows: WorkflowListRow[]): FacetDefinition<WorkflowListRow>[] {
    const creatorNames = new Map<string, string>()
    for (const { workflow } of rows) {
        if (workflow.created_by) {
            creatorNames.set(workflow.created_by.uuid, workflow.created_by.first_name || workflow.created_by.email)
        }
    }

    return [
        {
            key: 'status',
            label: 'Status',
            description: 'Draft, active or archived',
            showOnFocus: true,
            order: 1,
            getValues: (row) => [row.workflow.status],
            formatValue: labelFrom(STATUS_LABELS),
        },
        {
            key: 'type',
            label: 'Type',
            description: 'Messaging, automation or loop',
            showOnFocus: true,
            order: 2,
            getValues: (row) => [row.workflow.type],
            formatValue: labelFrom(TYPE_LABELS),
        },
        {
            key: 'trigger',
            label: 'Trigger',
            description: 'What starts the workflow',
            showOnFocus: true,
            order: 3,
            getValues: (row) => (row.triggerType ? [row.triggerType] : []),
            formatValue: labelFrom(TRIGGER_LABELS),
        },
        {
            key: 'owner',
            label: 'Owner',
            description: 'Owner: @name in the description, else the creator',
            showOnFocus: true,
            order: 4,
            getValues: (row) => row.owners,
            formatValue: (value) => `@${value}`,
        },
        {
            key: 'health',
            label: 'Health',
            description: 'Failed runs in the last 7 days',
            showOnFocus: true,
            order: 5,
            getValues: (row) => [row.health],
            formatValue: labelFrom(HEALTH_LABELS),
        },
        {
            key: 'created-by',
            label: 'Created by',
            description: 'Who created it',
            order: 6,
            getValues: (row) => (row.workflow.created_by ? [row.workflow.created_by.uuid] : []),
            formatValue: (value) => creatorNames.get(value) ?? value,
        },
    ]
}
