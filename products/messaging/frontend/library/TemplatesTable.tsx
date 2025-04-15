import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { hogFunctionUrl } from 'scenes/pipeline/hogfunctions/urls'

import { Message } from './messagesLogic'
import { templatesLogic } from './templatesLogic'

export function TemplatesTable(): JSX.Element {
    const { templates, templatesLoading } = useValues(templatesLogic)
    const { deleteTemplate } = useActions(templatesLogic)

    const columns: LemonTableColumns<Message> = [
        {
            title: 'Name',
            render: (_, item) => {
                return (
                    <LemonTableLink
                        to={hogFunctionUrl(item.type, item.id, item.template_id, item.kind)}
                        title={item.name}
                        description={item.description}
                    />
                )
            },
        },
        createdByColumn<Message>() as LemonTableColumn<Message, keyof Message | undefined>,
        createdAtColumn<Message>() as LemonTableColumn<Message, keyof Message | undefined>,
        {
            width: 0,
            render: function Render(_, message: Message) {
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
            <h2>Templates</h2>
            <LemonTable dataSource={templates} loading={templatesLoading} columns={columns} />
        </div>
    )
}
