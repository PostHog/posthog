import './MessageTemplatesGrid.scss'

import { useActions, useMountedLogic, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import * as readingIsMagicPng from '@posthog/brand/hoggies/png/reading-is-magic'
import { IconLetter, IconTrash, IconWebhooks } from '@posthog/icons'

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

const HedgehogReadingIsMagic = pngHoggie(readingIsMagicPng)

export function MessageTemplatesTable(): JSX.Element {
    useMountedLogic(messageTemplatesLogic)
    const { filteredTemplates, templates, templatesLoading, search, createdByFilter, typeFilter, hasActiveFilters } =
        useValues(messageTemplatesLogic)
    const {
        deleteTemplate,
        createTemplate,
        duplicateTemplate,
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

    const showProductIntroduction = !templatesLoading && templates.length === 0
    const showNoResults = !templatesLoading && templates.length > 0 && filteredTemplates.length === 0

    return (
        <div className="templates-section" data-attr="message-templates-table">
            {showProductIntroduction && (
                <ProductIntroduction
                    productName="Template library"
                    thingName="template"
                    titleOverride="Save your first template"
                    description="Templates are emails, webhooks, and destinations you set up once and reuse across your workflows. Start one here, or open a workflow and save a step you already configured."
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
                        ]}
                        data-attr="templates-type-filter"
                    />
                </div>
                <div className="flex items-center gap-2">
                    <span className="text-secondary whitespace-nowrap">Created by:</span>
                    <MemberSelect value={createdByFilter} onChange={(user) => setCreatedByFilter(user?.id ?? null)} />
                </div>
            </div>
            {templatesLoading ? (
                <Spinner className="text-6xl" />
            ) : showNoResults ? (
                <div className="flex flex-col items-center gap-2 py-8 text-center" data-attr="templates-no-results">
                    <p className="mb-0 text-secondary">
                        {hasActiveFilters ? 'No templates match your filters.' : 'No templates to show right now.'}
                    </p>
                    {hasActiveFilters && (
                        <LemonButton type="secondary" size="small" onClick={clearFilters}>
                            Clear filters
                        </LemonButton>
                    )}
                </div>
            ) : (
                <div className="MessageTemplatesGrid">
                    {filteredTemplates.map((template, index) => (
                        <MessageTemplateCard
                            key={template.id}
                            template={template}
                            index={index}
                            hogFunctionTemplate={
                                template.content.function?.template_id
                                    ? destinationTemplatesById[template.content.function.template_id]
                                    : undefined
                            }
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
