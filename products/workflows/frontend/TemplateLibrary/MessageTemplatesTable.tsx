import { useActions, useMountedLogic, useValues } from 'kea'
import { router } from 'kea-router'

import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { ReadingHog } from 'lib/components/hedgehogs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import MaxTool from 'scenes/max/MaxTool'
import { urls } from 'scenes/urls'

import { MessageTemplate, messageTemplatesLogic } from './messageTemplatesLogic'

export function MessageTemplatesTable(): JSX.Element {
    useMountedLogic(messageTemplatesLogic)
    const { templates, templatesLoading } = useValues(messageTemplatesLogic)
    const { deleteTemplate, createTemplate, duplicateTemplate } = useActions(messageTemplatesLogic)

    const columns: LemonTableColumns<MessageTemplate> = [
        {
            title: 'Name',
            render: (_, item) => {
                return (
                    <LemonTableLink
                        to={urls.workflowsLibraryTemplate(item.id)}
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
                                    data-attr="message-template-duplicate"
                                    fullWidth
                                    onClick={() => duplicateTemplate(message)}
                                >
                                    Duplicate
                                </LemonButton>
                                <LemonButton
                                    data-attr="message-template-delete"
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

    const showProductIntroduction = !templatesLoading && templates.length === 0

    return (
        <div className="templates-section">
            {showProductIntroduction && (
                <ProductIntroduction
                    productName="Message template"
                    thingName="message template"
                    description="Create and manage reusable message templates for your workflows."
                    docsURL="https://posthog.com/docs/workflows"
                    action={() => {
                        router.actions.push(urls.workflowsLibraryTemplateNew())
                    }}
                    customHog={ReadingHog}
                    isEmpty
                />
            )}
            <MaxTool
                identifier="create_message_template"
                context={{}}
                callback={(toolOutput: any) => {
                    createTemplate({ template: JSON.parse(toolOutput) })
                }}
            >
                <div className="relative" />
            </MaxTool>
            <LemonTable dataSource={templates} loading={templatesLoading} columns={columns} />
        </div>
    )
}
