import { useActions, useValues } from 'kea'

import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { messageTemplatesLogic } from '../../TemplateLibrary/messageTemplatesLogic'
import { transactionalEmailMetricsLogic } from './transactionalEmailMetricsLogic'

export function TransactionalEmailResultsEmailPicker(): JSX.Element {
    const { resultsQuery, resultsEmailOptions } = useValues(transactionalEmailMetricsLogic)
    const { setResultsQuery } = useActions(transactionalEmailMetricsLogic)
    const { templatesLoading } = useValues(messageTemplatesLogic)

    return (
        <LemonInputSelect
            mode="single"
            size="small"
            placeholder="Choose an email"
            value={resultsQuery.workflowId ? [resultsQuery.workflowId] : []}
            onChange={(values) => setResultsQuery({ workflowId: values[0] ?? null })}
            options={resultsEmailOptions.map((option) => ({
                key: option.workflowId,
                label: option.name,
                labelComponent: (
                    <span className="flex w-full items-center justify-between gap-4">
                        <span className="truncate">{option.name}</span>
                        <span className="text-secondary text-xs whitespace-nowrap">
                            {option.sent > 0 ? `${humanFriendlyNumber(option.sent)} sent` : 'No sends in this period'}
                        </span>
                    </span>
                ),
            }))}
            loading={templatesLoading}
            className="min-w-48"
            data-attr="transactional-email-results-email"
        />
    )
}
