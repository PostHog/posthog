import { useActions, useValues } from 'kea'

import { IconCheck, IconEllipsis } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { OPTIONAL_COLUMNS, OptionalColumn, workflowsListV2Logic } from './workflowsListV2Logic'

const COLUMN_LABELS: Record<OptionalColumn, string> = {
    type: 'Type',
    trigger: 'Trigger',
    owner: 'Owner',
    created_by: 'Created by',
    last_7_days: 'Last 7 days',
    health: 'Health',
}

/** The "…" menu next to "New workflow": picks the optional columns of the list. */
export function WorkflowsListV2ColumnsMenu(): JSX.Element {
    const { visibleColumns } = useValues(workflowsListV2Logic)
    const { toggleColumn, resetColumns } = useActions(workflowsListV2Logic)

    return (
        <LemonMenu
            closeOnClickInside={false}
            items={[
                {
                    title: 'Columns',
                    items: OPTIONAL_COLUMNS.map((column) => ({
                        label: COLUMN_LABELS[column],
                        icon: visibleColumns.includes(column) ? <IconCheck /> : <span className="w-4" />,
                        onClick: () => toggleColumn(column),
                        'data-attr': `workflows-list-v2-column-${column}`,
                    })),
                },
                {
                    items: [
                        {
                            label: 'Reset to default columns',
                            onClick: resetColumns,
                            'data-attr': 'workflows-list-v2-reset-columns',
                        },
                    ],
                },
            ]}
        >
            <LemonButton
                size="small"
                type="secondary"
                icon={<IconEllipsis />}
                aria-label="List options"
                data-attr="workflows-list-v2-options"
            />
        </LemonMenu>
    )
}
