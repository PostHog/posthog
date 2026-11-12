import { useActions, useValues } from 'kea'

import { LemonBanner, LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'

import { TransactionalTemplatesLoadError } from '../TransactionalTemplatesLoadError'
import { transactionalTemplatesLogic } from '../transactionalTemplatesLogic'
import { transactionalEmailMetricsLogic } from './transactionalEmailMetricsLogic'
import { TransactionalEmailResultsStats } from './TransactionalEmailResultsStats'

export function TransactionalEmailResults(): JSX.Element {
    const { resultsQuery, results, resultsLoading, resultsFailed, canLoadResults } =
        useValues(transactionalEmailMetricsLogic)
    const { setResultsQuery, loadResults } = useActions(transactionalEmailMetricsLogic)
    const { transactionalTemplates, transactionalTemplatesFailed } = useValues(transactionalTemplatesLogic)

    const emailOptions = transactionalTemplates
        .filter((template) => template.transactional_hog_flow_id)
        .map((template) => ({
            value: template.transactional_hog_flow_id as string,
            label: template.name || 'Unnamed email',
        }))

    return (
        <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-2 text-sm">
                <span>Of everyone who got</span>
                <LemonSelect
                    size="small"
                    placeholder="Choose an email"
                    value={resultsQuery.workflowId}
                    onChange={(workflowId) => setResultsQuery({ workflowId })}
                    options={emailOptions}
                    data-attr="transactional-email-results-email"
                />
                <span>how many did</span>
                <TaxonomicPopover
                    groupType={TaxonomicFilterGroupType.Events}
                    value={resultsQuery.event ?? undefined}
                    onChange={(event) => setResultsQuery({ event: event ? String(event) : null })}
                    placeholder="Choose an event"
                    size="small"
                    data-attr="transactional-email-results-event"
                />
                <span>within</span>
                <LemonInput
                    type="number"
                    size="small"
                    min={1}
                    max={30}
                    value={resultsQuery.windowDays}
                    onChange={(windowDays) => {
                        // Clearing the field gives NaN, which the API rejects.
                        if (windowDays !== undefined && Number.isFinite(windowDays)) {
                            setResultsQuery({ windowDays: Math.min(Math.max(Math.round(windowDays), 1), 30) })
                        }
                    }}
                    className="w-16"
                    data-attr="transactional-email-results-window"
                />
                <span>days, with revenue from</span>
                <TaxonomicPopover
                    groupType={TaxonomicFilterGroupType.EventProperties}
                    value={resultsQuery.revenueProperty ?? undefined}
                    onChange={(property) => setResultsQuery({ revenueProperty: property ? String(property) : null })}
                    placeholder="No revenue property"
                    allowClear
                    size="small"
                    data-attr="transactional-email-results-revenue"
                />
            </div>
            {transactionalTemplatesFailed ? (
                <TransactionalTemplatesLoadError
                    message="Your emails couldn't load, so there's nothing to pick yet. Check your connection and try again."
                    dataAttr="transactional-email-results-templates-retry"
                />
            ) : !canLoadResults ? (
                <p className="text-secondary text-sm m-0">
                    Choose an email and the event that counts as a conversion, such as a signup or a purchase.
                </p>
            ) : resultsFailed && !resultsLoading ? (
                <LemonBanner
                    type="error"
                    action={{
                        children: 'Try again',
                        onClick: () => loadResults(),
                        'data-attr': 'transactional-email-results-retry',
                    }}
                >
                    These results couldn't load. Try again, or pick a shorter window.
                </LemonBanner>
            ) : !resultsLoading && results?.recipients === 0 ? (
                <p className="text-secondary text-sm m-0">
                    Nobody was sent this email in this period, or the sends named no distinct ID.
                </p>
            ) : (
                <TransactionalEmailResultsStats />
            )}
        </div>
    )
}
