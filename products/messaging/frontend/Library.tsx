import { IconPlusSmall } from '@posthog/icons'
import { useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonTable, LemonTableColumn } from 'lib/lemon-ui/LemonTable'
import { createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { hogFunctionUrl } from 'scenes/pipeline/hogfunctions/urls'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { libraryLogic, Message } from './libraryLogic'
import { MessagingTabs } from './MessagingTabs'

export function Library(): JSX.Element {
    const { messages, templates, messagesLoading, templatesLoading } = useValues(libraryLogic)

    return (
        <div className="messaging-library">
            <MessagingTabs key="tabs" />
            <PageHeader
                caption="Create and manage messages"
                buttons={
                    <LemonButton
                        data-attr="new-message-button"
                        icon={<IconPlusSmall />}
                        size="small"
                        type="primary"
                        to={urls.messagingLibraryTemplateNew()}
                    >
                        New Template
                    </LemonButton>
                }
            />

            <div className="templates-section">
                <h2>Templates</h2>
                <LemonTable
                    dataSource={templates}
                    loading={templatesLoading}
                    columns={[
                        {
                            title: 'Name',
                            dataIndex: 'name',
                            render: (name: string | undefined, template: any) => (
                                <LemonButton to={urls.messagingLibraryTemplate(template.id)}>{name}</LemonButton>
                            ),
                        },
                        {
                            title: 'Description',
                            dataIndex: 'description',
                        },
                        {
                            title: 'Last Modified',
                            dataIndex: 'updated_at',
                            render: (date: string | undefined) => (date ? new Date(date).toLocaleString() : ''),
                        },
                    ]}
                />
            </div>

            <LemonDivider />

            <div className="messages-section">
                <h2>Messages</h2>
                <LemonTable
                    dataSource={messages}
                    loading={messagesLoading}
                    columns={[
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
                                                    to={urls.messagingLibraryTemplateFromMessage(message.id)}
                                                    data-attr="feature-flag-duplicate"
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
                    ]}
                />
            </div>
        </div>
    )
}

export const scene: SceneExport = {
    component: Library,
    logic: libraryLogic,
}
