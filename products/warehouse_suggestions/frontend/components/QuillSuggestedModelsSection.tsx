import { Heading, Text, cn } from '@posthog/quill'

import {
    QUILL_ASSIGNEE_CELL_CLASS,
    QUILL_ASSIGNEE_COLUMNS_CLASS,
    QUILL_SAVING_COLUMNS_CLASS,
    QuillRowSelectionProps,
} from './QuillSuggestionRow'
import { SuggestedModelsSectionProps } from './SuggestedModelsSection'

export function QuillSuggestedModelsSection({
    title,
    description,
    showsSaving = true,
    children,
    selection,
    assigneeColumn,
    showsAssigneeLabel = false,
}: SuggestedModelsSectionProps & QuillRowSelectionProps & { showsAssigneeLabel?: boolean }): JSX.Element {
    return (
        <section aria-label={title}>
            <div
                className={cn(
                    'grid grid-cols-1 items-end px-3 pt-4 pb-1',
                    QUILL_SAVING_COLUMNS_CLASS,
                    assigneeColumn && QUILL_ASSIGNEE_COLUMNS_CLASS
                )}
            >
                <div className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-0.5">
                    {selection && <span className="flex translate-y-0.5 self-center">{selection}</span>}
                    <Heading size="sm" render={<h4 className="m-0" />}>
                        {title}
                    </Heading>
                    <Text size="xs" variant="muted" render={<span />}>
                        {description}
                    </Text>
                </div>
                {showsSaving && (
                    <Text
                        size="xs"
                        variant="muted"
                        render={<span />}
                        className="hidden text-right @min-[36rem]/suggestions:block"
                    >
                        Main saving a month
                    </Text>
                )}
                {assigneeColumn && showsAssigneeLabel && (
                    <Text size="xs" variant="muted" render={<span />} className={cn(QUILL_ASSIGNEE_CELL_CLASS, 'pl-2')}>
                        Assignee
                    </Text>
                )}
            </div>
            <div className="divide-y divide-border">{children}</div>
        </section>
    )
}
