import { useActions, useMountedLogic, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { urls } from 'scenes/urls'

import { MessageTemplate, templatesLogic } from './templatesLogic'

export function TemplatesTable(): JSX.Element {
    useMountedLogic(templatesLogic)
    const { templates, templatesLoading } = useValues(templatesLogic)
    const { deleteTemplate } = useActions(templatesLogic)

    const columns: LemonTableColumns<MessageTemplate> = [
        {
            title: 'Name',
            render: (_, item) => {
                return (
                    <LemonTableLink
                        to={urls.messagingLibraryTemplate(item.id)}
                        title={item.name}
                        description={item.description}
                    />
                )
            },
        },
        createdByColumn<MessageTemplate>() as LemonTableColumn<MessageTemplate, keyof MessageTemplate | undefined>,
        createdAtColumn<MessageTemplate>() as LemonTableColumn<MessageTemplate, keyof MessageTemplate | undefined>,
        {
            width: 0,
            render: function Render(_, message: MessageTemplate) {
                return (
                    <More
                        overlay={
                            <>
                                <LemonButton
                                    data-attr="feature-flag-duplicate"
                                    fullWidth
                                    status="danger"
                                    onClick={() => deleteTemplate(message)}
                                >
                                    Delete
                                </LemonButton>
                            </>
                        }
                    />
                )
            },
        },
    ]

    return (
        <div className="templates-section">
            <LemonTable dataSource={templates} loading={templatesLoading} columns={columns} />
        </div>
    )
}
