import { IconPlusSmall } from '@posthog/icons'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { urls } from 'scenes/urls'

import { MessagingTabs } from './MessagingTabs'

export function Library(): JSX.Element {
    const menuItems = [
        { label: 'New Template', to: urls.messagingLibraryNew() },
        { label: 'New Message', to: urls.messagingLibraryMessageNew() },
    ]

    return (
        <div className="messaging-library">
            <MessagingTabs key="tabs" />
            <PageHeader
                caption="Create and manage messages"
                buttons={
                    <LemonMenu items={menuItems}>
                        <LemonButton
                            data-attr="new-message-button"
                            icon={<IconPlusSmall />}
                            size="small"
                            type="primary"
                        >
                            New
                        </LemonButton>
                    </LemonMenu>
                }
            />

            <div className="templates-section">
                <h2>Templates</h2>
                <LemonTable
                    dataSource={[]}
                    loading={false}
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
                            dataIndex: 'last_modified',
                            render: (date: string | undefined) => (date ? new Date(date).toLocaleString() : ''),
                        },
                    ]}
                />
            </div>

            <LemonDivider />

            <div className="messages-section">
                <h2>Messages</h2>
                <LemonTable
                    dataSource={[]}
                    loading={false}
                    columns={[
                        {
                            title: 'Subject',
                            dataIndex: 'subject',
                            render: (subject: string | number | undefined, message: any) => (
                                <LemonButton to={urls.messagingLibraryMessage(message.id)}>{subject}</LemonButton>
                            ),
                        },
                        {
                            title: 'Status',
                            dataIndex: 'status',
                        },
                        {
                            title: 'Recipients',
                            dataIndex: 'recipients_count',
                        },
                        {
                            title: 'Created',
                            dataIndex: 'created_at',
                            render: (date: string | number | undefined) => (
                                <p>{date ? new Date(date).toLocaleString() : ''}</p>
                            ),
                        },
                        {
                            title: 'Sent',
                            dataIndex: 'sent_at',
                            render: (date: string | number | undefined) =>
                                date ? new Date(date).toLocaleString() : 'Not sent',
                        },
                    ]}
                />
            </div>
        </div>
    )
}
