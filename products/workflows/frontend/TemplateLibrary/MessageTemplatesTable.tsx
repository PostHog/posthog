import './MessageTemplatesGrid.scss'

import { useActions, useMountedLogic, useValues } from 'kea'
import { router } from 'kea-router'

import * as readingIsMagicPng from '@posthog/brand/hoggies/png/reading-is-magic'
import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonCheckbox } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { MemberSelect } from 'lib/components/MemberSelect'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { TagSelect } from 'lib/components/TagSelect'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import MaxTool from 'scenes/max/MaxTool'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { MessageTemplateCard } from './MessageTemplateCard'
import { messageTemplatesLogic, saveTemplateTags } from './messageTemplatesLogic'
import { newTemplateAgentLogic } from './newTemplateAgentLogic'

const HedgehogReadingIsMagic = pngHoggie(readingIsMagicPng)

export function MessageTemplatesTable(): JSX.Element {
    useMountedLogic(messageTemplatesLogic)
    const {
        filteredTemplates,
        templates,
        templatesLoading,
        search,
        createdByFilter,
        transactionalOnly,
        tagsFilter,
        tags: allTags,
    } = useValues(messageTemplatesLogic)
    const {
        deleteTemplate,
        createTemplate,
        duplicateTemplate,
        setSearch,
        setCreatedByFilter,
        setTransactionalOnly,
        setTagsFilter,
    } = useActions(messageTemplatesLogic)
    const transactionalEmailsEnabled = useFeatureFlag('WORKFLOWS_TRANSACTIONAL_EMAIL_API')
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
                <div className="flex items-center gap-2">
                    <span className="text-secondary whitespace-nowrap">Tags:</span>
                    <TagSelect
                        size="small"
                        defaultLabel="Any tags"
                        value={tagsFilter}
                        onChange={setTagsFilter}
                        listDataAttr="templates-tags-filter-list"
                    />
                </div>
                {transactionalEmailsEnabled && (
                    <LemonCheckbox
                        label="Transactional only"
                        checked={transactionalOnly}
                        onChange={setTransactionalOnly}
                        bordered
                        size="small"
                        data-attr="templates-transactional-only"
                    />
                )}
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
                            onTagClick={(tag) => !tagsFilter.includes(tag) && setTagsFilter([...tagsFilter, tag])}
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
                                                    label: 'Edit tags',
                                                    onClick: () =>
                                                        LemonDialog.openForm({
                                                            title: 'Edit tags',
                                                            // A rejected save keeps the dialog open, so the
                                                            // selection survives a validation error or a retry.
                                                            shouldAwaitSubmit: true,
                                                            initialValues: { tags: [...(template.tags ?? [])] },
                                                            content: (
                                                                <LemonField name="tags">
                                                                    <LemonInputSelect
                                                                        mode="multiple"
                                                                        allowCustomValues
                                                                        options={allTags.map((tag) => ({
                                                                            key: tag,
                                                                            label: tag,
                                                                        }))}
                                                                        placeholder='try "growth"'
                                                                        autoFocus
                                                                        data-attr="template-tags-input"
                                                                    />
                                                                </LemonField>
                                                            ),
                                                            onSubmit: async ({ tags }) => {
                                                                try {
                                                                    await saveTemplateTags(template, tags)
                                                                } catch (error: any) {
                                                                    lemonToast.error(
                                                                        `Failed to save tags: ${error?.detail || error?.message || 'Unknown error'}`
                                                                    )
                                                                    throw error
                                                                }
                                                            },
                                                        }),
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
