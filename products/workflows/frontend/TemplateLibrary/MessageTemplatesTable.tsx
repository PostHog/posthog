import './MessageTemplatesGrid.scss'

import { useActions, useMountedLogic, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import * as readingIsMagicPng from '@posthog/brand/hoggies/png/reading-is-magic'
import { IconLetter, IconTrash, IconWebhooks } from '@posthog/icons'
import { LemonDialog } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { MemberSelect } from 'lib/components/MemberSelect'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { hogFunctionTemplateListLogic } from 'scenes/hog-functions/list/hogFunctionTemplateListLogic'
import MaxTool from 'scenes/max/MaxTool'
import { urls } from 'scenes/urls'

import { MessageTemplateCard } from './MessageTemplateCard'
import { messageTemplatesLogic } from './messageTemplatesLogic'
import { WorkflowTemplateCard } from './WorkflowTemplateCard'

const HedgehogReadingIsMagic = pngHoggie(readingIsMagicPng)

export function MessageTemplatesTable(): JSX.Element {
    useMountedLogic(messageTemplatesLogic)
    const {
        libraryItems,
        libraryLoading,
        isLibraryEmpty,
        savedWorkflowTemplates,
        search,
        createdByFilter,
        typeFilter,
    } = useValues(messageTemplatesLogic)
    const {
        deleteTemplate,
        createTemplate,
        duplicateTemplate,
        deleteHogflowTemplate,
        setSearch,
        setCreatedByFilter,
        setTypeFilter,
        clearFilters,
    } = useActions(messageTemplatesLogic)

    // Destination templates provide the icon and name shown on saved webhook/destination cards
    const destinationTemplatesLogic = hogFunctionTemplateListLogic({ type: 'destination' })
    const { templates: destinationTemplates } = useValues(destinationTemplatesLogic)
    const { loadHogFunctionTemplates } = useActions(destinationTemplatesLogic)
    useEffect(() => {
        loadHogFunctionTemplates()
    }, [loadHogFunctionTemplates])
    const destinationTemplatesById = Object.fromEntries(destinationTemplates.map((t) => [t.id, t]))

    const showNoResults = !libraryLoading && !isLibraryEmpty && libraryItems.length === 0
    const noWorkflowTemplatesYet = typeFilter === 'workflow' && savedWorkflowTemplates.length === 0

    return (
        <div className="templates-section" data-attr="message-templates-table">
            {isLibraryEmpty && (
                <ProductIntroduction
                    productName="Template library"
                    thingName="template"
                    titleOverride="Save your first template"
                    description="Templates are emails, webhooks, and whole workflows you set up once and reuse. Start an email or webhook here. To add a workflow, open one and save it as a template."
                    docsURL="https://posthog.com/docs/workflows"
                    actionElementOverride={
                        <>
                            <LemonButton
                                type="primary"
                                icon={<IconLetter />}
                                onClick={() => router.actions.push(urls.workflowsLibraryTemplateNew())}
                                data-attr="empty-state-new-email-template"
                            >
                                New email template
                            </LemonButton>
                            <LemonButton
                                type="secondary"
                                icon={<IconWebhooks />}
                                onClick={() => router.actions.push(urls.workflowsLibraryTemplateNewFunction())}
                                data-attr="empty-state-new-function-template"
                            >
                                New webhook template
                            </LemonButton>
                        </>
                    }
                    customHog={HedgehogReadingIsMagic}
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
                <LemonInput
                    type="search"
                    placeholder="Search templates"
                    value={search}
                    onChange={setSearch}
                    data-attr="templates-search"
                />
                <div className="flex items-center gap-2">
                    <span className="text-secondary whitespace-nowrap">Type:</span>
                    <LemonSelect
                        value={typeFilter}
                        onChange={setTypeFilter}
                        options={[
                            { value: 'all', label: 'All' },
                            { value: 'email', label: 'Emails' },
                            { value: 'function', label: 'Webhooks & destinations' },
                            { value: 'workflow', label: 'Workflows' },
                        ]}
                        data-attr="templates-type-filter"
                    />
                </div>
                <div className="flex items-center gap-2">
                    <span className="text-secondary whitespace-nowrap">Created by:</span>
                    <MemberSelect value={createdByFilter} onChange={(user) => setCreatedByFilter(user?.id ?? null)} />
                </div>
            </div>
            {libraryLoading ? (
                <Spinner className="text-6xl" />
            ) : showNoResults ? (
                <div className="flex flex-col items-center gap-2 py-8 text-center" data-attr="templates-no-results">
                    {noWorkflowTemplatesYet ? (
                        <>
                            <p className="mb-0 text-secondary">You haven't saved a workflow template yet.</p>
                            <p className="mb-0 text-xs text-secondary">
                                Open a workflow and choose "Save as workflow template" to keep it here.
                            </p>
                        </>
                    ) : (
                        <p className="mb-0 text-secondary">No templates match your filters.</p>
                    )}
                    <LemonButton type="secondary" size="small" onClick={clearFilters}>
                        Clear filters
                    </LemonButton>
                </div>
            ) : (
                <div className="MessageTemplatesGrid">
                    {libraryItems.map((item, index) =>
                        item.kind === 'workflow' ? (
                            <WorkflowTemplateCard
                                key={`workflow-${item.template.id}`}
                                template={item.template}
                                index={index}
                                onClick={() =>
                                    router.actions.push(urls.workflowNew(), { editTemplateId: item.template.id })
                                }
                                actions={
                                    <More
                                        size="small"
                                        overlay={
                                            <LemonMenuOverlay
                                                items={[
                                                    {
                                                        label: 'New workflow from this',
                                                        onClick: () =>
                                                            router.actions.push(urls.workflowNew(), {
                                                                templateId: item.template.id,
                                                            }),
                                                    },
                                                    {
                                                        label: 'Delete',
                                                        status: 'danger' as const,
                                                        icon: <IconTrash />,
                                                        onClick: () =>
                                                            LemonDialog.open({
                                                                title: 'Delete template?',
                                                                description: `"${item.template.name}" will be removed from the library. Workflows already created from it are not affected.`,
                                                                primaryButton: {
                                                                    children: 'Delete',
                                                                    status: 'danger',
                                                                    onClick: () => deleteHogflowTemplate(item.template),
                                                                },
                                                                secondaryButton: { children: 'Cancel' },
                                                            }),
                                                    },
                                                ]}
                                            />
                                        }
                                    />
                                }
                            />
                        ) : (
                            <MessageTemplateCard
                                key={`message-${item.template.id}`}
                                template={item.template}
                                index={index}
                                hogFunctionTemplate={
                                    item.template.content.function?.template_id
                                        ? destinationTemplatesById[item.template.content.function.template_id]
                                        : undefined
                                }
                                onClick={() => router.actions.push(urls.workflowsLibraryTemplate(item.template.id))}
                                actions={
                                    <More
                                        size="small"
                                        overlay={
                                            <LemonMenuOverlay
                                                items={[
                                                    {
                                                        label: 'Duplicate',
                                                        onClick: () => duplicateTemplate(item.template),
                                                    },
                                                    {
                                                        label: 'Delete',
                                                        status: 'danger' as const,
                                                        icon: <IconTrash />,
                                                        onClick: () => deleteTemplate(item.template),
                                                    },
                                                ]}
                                            />
                                        }
                                    />
                                }
                            />
                        )
                    )}
                </div>
            )}
        </div>
    )
}
