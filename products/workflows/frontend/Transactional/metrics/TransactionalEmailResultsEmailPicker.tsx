import { useActions, useValues } from 'kea'

import { LemonSearchableSelect } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import { messageTemplatesLogic } from '../../TemplateLibrary/messageTemplatesLogic'
import { transactionalEmailMetricsLogic } from './transactionalEmailMetricsLogic'

export function TransactionalEmailResultsEmailPicker(): JSX.Element {
    const { resultsQuery, resultsEmailOptions } = useValues(transactionalEmailMetricsLogic)
    const { setResultsQuery } = useActions(transactionalEmailMetricsLogic)
    const { templatesLoading } = useValues(messageTemplatesLogic)
    // Searching drops the chosen email from the options, so the button would show its ID.
    const chosenName = resultsEmailOptions.find((option) => option.workflowId === resultsQuery.workflowId)?.name

    return (
        <LemonSearchableSelect
            size="small"
            placeholder="Choose an email"
            searchPlaceholder="Search emails"
            noResultsMessage="No emails match"
            value={resultsQuery.workflowId}
            onChange={(workflowId) => setResultsQuery({ workflowId })}
            options={resultsEmailOptions.map((option) => ({
                value: option.workflowId,
                label: option.name,
                labelInMenu: (
                    <span className="flex w-full items-center justify-between gap-4">
                        <span className="truncate">{option.name}</span>
                        <span className="text-secondary text-xs whitespace-nowrap">
                            {option.sent > 0 ? `${humanFriendlyNumber(option.sent)} sent` : 'No sends in this period'}
                        </span>
                    </span>
                ),
            }))}
            renderButtonContent={(leaf) => chosenName ?? leaf?.label ?? 'Choose an email'}
            loading={templatesLoading}
            dropdownMatchSelectWidth={false}
            data-attr="transactional-email-results-email"
            searchInputDataAttr="transactional-email-results-email-search"
        />
    )
}
