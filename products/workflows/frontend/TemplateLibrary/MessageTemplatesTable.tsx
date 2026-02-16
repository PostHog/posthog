import './MessageTemplatesGrid.scss'

import { useActions, useMountedLogic, useValues } from 'kea'
import { router } from 'kea-router'

import { IconTrash } from '@posthog/icons'

import { MemberSelect } from 'lib/components/MemberSelect'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { ReadingHog } from 'lib/components/hedgehogs'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { Spinner } from 'lib/lemon-ui/Spinner'
import MaxTool from 'scenes/max/MaxTool'
import { urls } from 'scenes/urls'

import { MessageTemplateCard } from './MessageTemplateCard'
import { messageTemplatesLogic } from './messageTemplatesLogic'

export function MessageTemplatesTable(): JSX.Element {
    useMountedLogic(messageTemplatesLogic)
    const { filteredTemplates, templates, templatesLoading, search, createdByFilter } = useValues(messageTemplatesLogic)
    const { deleteTemplate, createTemplate, duplicateTemplate, setSearch, setCreatedByFilter } =
        useActions(messageTemplatesLogic)

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
            <div className="flex items-center gap-2 mb-4">
                <LemonInput type="search" placeholder="Search templates" value={search} onChange={setSearch} />
                <div className="flex items-center gap-2">
                    <span className="text-secondary whitespace-nowrap">Created by:</span>
                    <MemberSelect value={createdByFilter} onChange={(user) => setCreatedByFilter(user?.id ?? null)} />
                </div>
            </div>
            {templatesLoading ? (
                <Spinner className="text-6xl" />
            ) : (
                <div className="MessageTemplatesGrid">
                    {filteredTemplates.map((template, index) => (
                        <MessageTemplateCard
                            key={template.id}
                            template={template}
                            index={index}
                            onClick={() => router.actions.push(urls.workflowsLibraryTemplate(template.id))}
                            actions={
                                <More
                                    size="small"
                                    overlay={
                                        <LemonMenuOverlay
                                            items={[
                                                {
                                                    label: 'Duplicate',
                                                    onClick: () => duplicateTemplate(template),
                                                },
                                                {
                                                    label: 'Delete',
                                                    status: 'danger' as const,
                                                    icon: <IconTrash />,
                                                    onClick: () => deleteTemplate(template),
                                                },
                                            ]}
                                        />
                                    }
                                />
                            }
                        />
                    ))}
                </div>
            )}
        </div>
    )
}
