import { useActions, useValues } from 'kea'

import { LemonBanner, LemonInput } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { messageTemplatesLogic } from '../../TemplateLibrary/messageTemplatesLogic'
import { transactionalEmailMetricsLogic } from './transactionalEmailMetricsLogic'
import { TransactionalEmailResultsStats } from './TransactionalEmailResultsStats'

export function TransactionalEmailResults(): JSX.Element {
    const {
        resultsQuery,
        results,
        resultsLoading,
        resultsFailed,
        canLoadResults,
        templatesFailed,
        resultsEmailOptions,
    } = useValues(transactionalEmailMetricsLogic)
    const { setResultsQuery, loadResults, loadTemplates } = useActions(transactionalEmailMetricsLogic)
    const { templatesLoading } = useValues(messageTemplatesLogic)

    return (
        <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-2 text-sm">
                {/* Each part of the sentence keeps its label and control together, so a narrow page breaks between parts. */}
                <span className="inline-flex items-center gap-2">
                    <span className="whitespace-nowrap">Of everyone who got</span>
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
                                        {option.sent > 0
                                            ? `${humanFriendlyNumber(option.sent)} sent`
                                            : 'No sends in this period'}
                                    </span>
                                </span>
                            ),
                        }))}
                        loading={templatesLoading}
                        className="min-w-48"
                        data-attr="transactional-email-results-email"
                    />
                </span>
                <span className="inline-flex items-center gap-2">
                    <span className="whitespace-nowrap">how many did</span>
                    <TaxonomicPopover
                        groupType={TaxonomicFilterGroupType.Events}
                        value={resultsQuery.event ?? undefined}
                        onChange={(event) => setResultsQuery({ event: event ? String(event) : null })}
                        placeholder="Choose an event"
                        size="small"
                        data-attr="transactional-email-results-event"
                    />
                </span>
                <span className="inline-flex items-center gap-2">
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
                    <span>days,</span>
                </span>
                <span className="inline-flex items-center gap-2">
                    <span className="whitespace-nowrap">with revenue from</span>
                    <TaxonomicPopover
                        groupType={TaxonomicFilterGroupType.EventProperties}
                        value={resultsQuery.revenueProperty ?? undefined}
                        onChange={(property) =>
                            setResultsQuery({ revenueProperty: property ? String(property) : null })
                        }
                        placeholder="No revenue property"
                        allowClear
                        size="small"
                        data-attr="transactional-email-results-revenue"
                    />
                </span>
            </div>
            {templatesFailed && !templatesLoading ? (
                <LemonBanner
                    type="error"
                    action={{
                        children: 'Try again',
                        onClick: () => loadTemplates(),
                        'data-attr': 'transactional-email-results-templates-retry',
                    }}
                >
                    Your emails couldn't load, so there's nothing to pick yet. Check your connection and try again.
                </LemonBanner>
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
