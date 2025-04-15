import { useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { hogFunctionUrl } from 'scenes/pipeline/hogfunctions/urls'
import { urls } from 'scenes/urls'

import { Message } from './messagesLogic'
import { messagesLogic } from './messagesLogic'

export function MessagesTable(): JSX.Element {
    const { messages, messagesLoading } = useValues(messagesLogic)

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
        {
            title: 'Type',
            render: (_, { template_id }) => {
                if (template_id === 'template-new-broadcast') {
                    return 'Broadcast'
                }
                return 'Campaign'
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
                                    to={urls.messagingLibraryTemplateFromMessage({
                                        name: message.name,
                                        description: message.description,
                                        inputs: {
                                            email_template: message.content,
                                        },
                                    })}
                                    data-attr="new-template-from-message"
                                    fullWidth
                                >
                                    New template from message
                                </LemonButton>
                            </>
                        }
                    />
                )
            },
        },
    ]

    return (
        <div className="messages-section">
            <h2>Messages</h2>
            <LemonTable dataSource={messages} loading={messagesLoading} columns={columns} />
        </div>
    )
}
