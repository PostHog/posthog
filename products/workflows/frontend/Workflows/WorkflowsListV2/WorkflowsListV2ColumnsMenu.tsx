import { useActions, useValues } from 'kea'

import { IconCheck, IconEllipsis } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { OPTIONAL_COLUMNS, OPTIONAL_COLUMN_TITLES } from './workflowListLabels'
import { workflowsListV2Logic } from './workflowsListV2Logic'

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
                        label: OPTIONAL_COLUMN_TITLES[column],
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
