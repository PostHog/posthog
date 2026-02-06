import './MessageTemplatesGrid.scss'

import { useActions, useMountedLogic, useValues } from 'kea'
import { router } from 'kea-router'

import { IconTrash } from '@posthog/icons'

import { FallbackCoverImage } from 'lib/components/FallbackCoverImage/FallbackCoverImage'
import { MemberSelect } from 'lib/components/MemberSelect'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { TZLabel } from 'lib/components/TZLabel'
import { ReadingHog } from 'lib/components/hedgehogs'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { Spinner } from 'lib/lemon-ui/Spinner'
import MaxTool from 'scenes/max/MaxTool'
import { urls } from 'scenes/urls'

import { MessageTemplate, messageTemplatesLogic } from './messageTemplatesLogic'

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
                        <MessageTemplateItem
                            key={template.id}
                            template={template}
                            index={index}
                            onClick={() => router.actions.push(urls.workflowsLibraryTemplate(template.id))}
                            onDuplicate={() => duplicateTemplate(template)}
                            onDelete={() => deleteTemplate(template)}
                        />
                    ))}
                </div>
            )}
        </div>
    )
}

function MessageTemplateItem({
    template,
    index,
    onClick,
    onDuplicate,
    onDelete,
}: {
    template: MessageTemplate
    index: number
    onClick: () => void
    onDuplicate: () => void
    onDelete: () => void
}): JSX.Element {
    const emailHtml = template.content?.email?.html

    return (
        <div
            className="cursor-pointer border rounded MessageTemplateItem flex flex-col relative"
            onClick={onClick}
            data-attr="message-template-item"
        >
            <div className="absolute top-2 right-2 z-10" onClick={(e) => e.stopPropagation()}>
                <More
                    size="small"
                    className="bg-white/20 dark:bg-white/10 backdrop-blur-sm hover:bg-white/40 dark:hover:bg-white/20 transition-colors"
                    overlay={
                        <LemonMenuOverlay
                            items={[
                                {
                                    label: 'Duplicate',
                                    onClick: onDuplicate,
                                },
                                {
                                    label: 'Delete',
                                    status: 'danger' as const,
                                    icon: <IconTrash />,
                                    onClick: onDelete,
                                },
                            ]}
                        />
                    }
                />
            </div>
            <div className="w-full overflow-hidden grow">
                {emailHtml ? (
                    <iframe
                        srcDoc={emailHtml}
                        sandbox=""
                        className="w-full h-full border-0 bg-white pointer-events-none"
                    />
                ) : (
                    <FallbackCoverImage src={undefined} alt="cover photo" index={index} className="h-full" />
                )}
            </div>

            <div className="px-2 py-2 border-t">
                <h5 className="mb-0.5">{template.name || 'Unnamed template'}</h5>
                {template.description && (
                    <p className="text-secondary text-xs line-clamp-1 mb-1">{template.description}</p>
                )}
                <div className="flex items-center gap-2 text-xs text-secondary">
                    {template.created_by && <ProfilePicture user={template.created_by} size="sm" showName />}
                    {template.created_by && template.created_at && <span>·</span>}
                    {template.created_at && <TZLabel time={template.created_at} />}
                </div>
            </div>
        </div>
    )
}
