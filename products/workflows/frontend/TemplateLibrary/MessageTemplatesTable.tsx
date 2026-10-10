import './MessageTemplatesGrid.scss'

import { useActions, useMountedLogic, useValues } from 'kea'
import { router } from 'kea-router'

import * as readingIsMagicPng from '@posthog/brand/hoggies/png/reading-is-magic'
import { IconPlus, IconTrash } from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import { MemberSelect } from 'lib/components/MemberSelect'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import MaxTool from 'scenes/max/MaxTool'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { MessageTemplateCard } from './MessageTemplateCard'
import { messageTemplatesLogic } from './messageTemplatesLogic'
import { newTemplateAgentLogic } from './newTemplateAgentLogic'

const HedgehogReadingIsMagic = pngHoggie(readingIsMagicPng)

export function MessageTemplatesTable(): JSX.Element {
    useMountedLogic(messageTemplatesLogic)
    const { filteredTemplates, templates, templatesLoading, search, createdByFilter } = useValues(messageTemplatesLogic)
    const { deleteTemplate, createTemplate, duplicateTemplate, setSearch, setCreatedByFilter } =
        useActions(messageTemplatesLogic)
    const { startNewTemplate } = useActions(newTemplateAgentLogic)

    const showProductIntroduction = !templatesLoading && templates.length === 0
    // Same check as the "New template" button in the header: the template API needs Editor access.
    const newTemplateDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.Workflow,
        AccessControlLevel.Editor
    )

    return (
        <div className="templates-section" data-attr="message-templates-table">
            {showProductIntroduction && (
                <ProductIntroduction
                    thingName="message template"
                    description="Create and manage reusable message templates for your workflows."
                    docsURL="https://posthog.com/docs/workflows"
                    action={startNewTemplate}
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
                    <span className="text-secondary whitespace-nowrap">Created by:</span>
                    <MemberSelect value={createdByFilter} onChange={(user) => setCreatedByFilter(user?.id ?? null)} />
                </div>
            </div>
            {templatesLoading ? (
                <Spinner className="text-6xl" />
            ) : (
                <div className="MessageTemplatesGrid">
                    {!showProductIntroduction && (
                        <button
                            type="button"
                            className={
                                newTemplateDisabledReason
                                    ? 'MessageTemplateItem cursor-not-allowed'
                                    : 'MessageTemplateItem cursor-pointer'
                            }
                            onClick={startNewTemplate}
                            disabled={!!newTemplateDisabledReason}
                            title={newTemplateDisabledReason ?? undefined}
                            data-attr="message-templates-new-card"
                        >
                            <div className="MessageTemplateItemInner flex flex-col items-center justify-center gap-2 rounded border border-dashed bg-surface-primary px-4 text-center text-secondary hover:text-primary">
                                <IconPlus className="text-3xl" />
                                <span className="font-semibold">New template</span>
                                {newTemplateDisabledReason && (
                                    <span className="text-xs">{newTemplateDisabledReason}</span>
                                )}
                            </div>
                        </button>
                    )}
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
