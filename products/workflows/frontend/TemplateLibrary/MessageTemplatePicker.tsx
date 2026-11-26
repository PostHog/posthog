import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonCard, Spinner } from '@posthog/lemon-ui'

import { MemberSelect } from 'lib/components/MemberSelect'
import { TagSelect } from 'lib/components/TagSelect'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'

import { MessageTemplateCard } from './MessageTemplateCard'
import { messageTemplatesLogic } from './messageTemplatesLogic'
import { MessageTemplate } from './types'

export function MessageTemplatePicker({
    onBlank,
    onPick,
}: {
    onBlank: () => void
    onPick: (template: MessageTemplate) => void
}): JSX.Element {
    const logic = messageTemplatesLogic({ listKey: 'template-picker' })
    const {
        templates,
        templatesLoading,
        hasActiveFilters,
        hasMoreTemplates,
        moreTemplatesLoading,
        search,
        createdByFilter,
        tagsFilter,
    } = useValues(logic)
    const { setSearch, setCreatedByFilter, setTagsFilter, loadMoreTemplates } = useActions(logic)

    return (
        <div className="flex flex-col gap-3">
            <div className="sticky top-0 z-10 flex flex-wrap gap-2 items-center pb-2 bg-surface-primary">
                <LemonInput
                    type="search"
                    placeholder="Search templates"
                    value={search}
                    onChange={setSearch}
                    className="flex-1 min-w-48"
                    autoFocus
                    data-attr="template-picker-search"
                />
                <MemberSelect
                    defaultLabel="Any creator"
                    value={createdByFilter}
                    onChange={(user) => setCreatedByFilter(user?.id ?? null)}
                />
                {(tagsFilter.length > 0 || templates.some((template) => template.tags?.length)) && (
                    <TagSelect
                        size="small"
                        defaultLabel="Any tags"
                        value={tagsFilter}
                        onChange={setTagsFilter}
                        listDataAttr="template-picker-tags-filter-list"
                    />
                )}
            </div>
            <div className="flex flex-wrap gap-3">
                <LemonCard
                    className="w-48 h-56 flex flex-col gap-2 items-center justify-center cursor-pointer"
                    onClick={onBlank}
                    data-attr="template-picker-blank"
                >
                    <IconPlus className="text-2xl" />
                    <span>Blank template</span>
                </LemonCard>
                {templates.map((template, index) => (
                    <div key={template.id} className="w-48 h-56">
                        <MessageTemplateCard template={template} index={index} onClick={() => onPick(template)} />
                    </div>
                ))}
            </div>
            {templatesLoading && templates.length === 0 && <Spinner className="text-2xl" />}
            {!templatesLoading && templates.length === 0 && hasActiveFilters && (
                <p className="text-secondary m-0" data-attr="template-picker-no-matches">
                    No templates match. Try another search or clear the filters.
                </p>
            )}
            {hasMoreTemplates && (
                <div className="flex justify-center">
                    <LemonButton
                        type="secondary"
                        onClick={loadMoreTemplates}
                        loading={moreTemplatesLoading}
                        data-attr="template-picker-load-more"
                    >
                        Load more templates
                    </LemonButton>
                </div>
            )}
        </div>
    )
}
