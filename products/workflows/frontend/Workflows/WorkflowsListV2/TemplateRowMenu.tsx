import { useActions } from 'kea'

import { IconTrash } from '@posthog/icons'
import { LemonMenuOverlay } from '@posthog/lemon-ui'

import { More } from 'lib/lemon-ui/LemonButton/More'

import { EmailTemplateRow } from './workflowListRows'
import { workflowsListV2Logic } from './workflowsListV2Logic'

/** The Library tab's actions for one email template row. */
export function TemplateRowMenu({ row }: { row: EmailTemplateRow }): JSX.Element {
    const { duplicateTemplate, deleteTemplate } = useActions(workflowsListV2Logic)
    return (
        <More
            overlay={
                <LemonMenuOverlay
                    items={[
                        { label: 'Duplicate', onClick: () => duplicateTemplate(row) },
                        {
                            label: 'Delete',
                            status: 'danger' as const,
                            icon: <IconTrash />,
                            onClick: () => deleteTemplate(row),
                        },
                    ]}
                />
            }
        />
    )
}
