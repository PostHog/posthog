import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonCard, Spinner } from '@posthog/lemon-ui'

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
        canLoadMoreTemplates,
        canRetryTemplates,
        moreTemplatesLoading,
    } = useValues(logic)
    const { loadMoreTemplates, loadTemplates } = useActions(logic)

    return (
        <div className="flex flex-col gap-3">
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
            {canRetryTemplates && (
                <div className="flex justify-center">
                    <LemonButton type="secondary" onClick={() => loadTemplates()} data-attr="template-picker-reload">
                        Reload templates
                    </LemonButton>
                </div>
            )}
            {canLoadMoreTemplates && (
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
