import { useActions, useValues } from 'kea'

import { IconCheck, IconEllipsis, IconUndo } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { OPTIONAL_COLUMNS, OPTIONAL_COLUMN_TITLES } from './workflowListLabels'
import { workflowsListV2Logic } from './workflowsListV2Logic'
import { workflowsSavedViewsLogic } from './workflowsSavedViewsLogic'

export function WorkflowsListV2ColumnsMenu(): JSX.Element {
    const { shownColumns } = useValues(workflowsListV2Logic)
    const { toggleColumn, resetColumns } = useActions(workflowsListV2Logic)
    const { available, myWorkflowsDeleted, saving, writeDisabledReason } = useValues(workflowsSavedViewsLogic)
    const { restoreMyWorkflows } = useActions(workflowsSavedViewsLogic)

    return (
        <LemonMenu
            closeOnClickInside={false}
            items={[
                {
                    title: 'Columns',
                    items: OPTIONAL_COLUMNS.map((column) => ({
                        label: (
                            <>
                                {OPTIONAL_COLUMN_TITLES[column]}
                                {shownColumns.includes(column) && <span className="sr-only">, shown</span>}
                            </>
                        ),
                        active: shownColumns.includes(column),
                        icon: shownColumns.includes(column) ? <IconCheck /> : <span className="w-4" />,
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
                        ...(available && myWorkflowsDeleted
                            ? [
                                  {
                                      label: 'Restore My workflows',
                                      icon: <IconUndo />,
                                      tooltip: 'Brings the view back for everyone in this project',
                                      onClick: restoreMyWorkflows,
                                      disabledReason: saving ? 'A view is being saved' : writeDisabledReason,
                                      'data-attr': 'workflows-combined-restore-shipped-views',
                                  },
                              ]
                            : []),
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
