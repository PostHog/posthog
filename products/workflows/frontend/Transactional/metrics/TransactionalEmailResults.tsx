import { useActions, useValues } from 'kea'

import { LemonBanner, LemonInput } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'

import { messageTemplatesLogic } from '../../TemplateLibrary/messageTemplatesLogic'
import { transactionalEmailMetricsLogic } from './transactionalEmailMetricsLogic'
import { TransactionalEmailResultsEmailPicker } from './TransactionalEmailResultsEmailPicker'
import { TransactionalEmailResultsStats } from './TransactionalEmailResultsStats'

// Clearing the field gives NaN, which the API rejects, so it changes nothing.
function clampWindowDays(windowDays: number | undefined): number | null {
    if (windowDays === undefined || !Number.isFinite(windowDays)) {
        return null
    }
    return Math.min(Math.max(Math.round(windowDays), 1), 30)
}

function ResultsField({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
    return (
        <label className="flex flex-col gap-1">
            <span className="text-xs text-secondary font-medium">{label}</span>
            {children}
        </label>
    )
}

export function TransactionalEmailResults(): JSX.Element {
    const { resultsQuery, results, resultsLoading, resultsFailed, canLoadResults, templatesFailed } =
        useValues(transactionalEmailMetricsLogic)
    const { setResultsQuery, loadResults, loadTemplates } = useActions(transactionalEmailMetricsLogic)
    const { templatesLoading } = useValues(messageTemplatesLogic)

    return (
        <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-end gap-3">
                <ResultsField label="Email sent">
                    <TransactionalEmailResultsEmailPicker />
                </ResultsField>
                <ResultsField label="Event done after">
                    <TaxonomicPopover
                        groupType={TaxonomicFilterGroupType.Events}
                        value={resultsQuery.event ?? undefined}
                        onChange={(event) => setResultsQuery({ event: event ? String(event) : null })}
                        placeholder="Choose an event"
                        size="small"
                        data-attr="transactional-email-results-event"
                    />
                </ResultsField>
                <ResultsField label="Within days">
                    <LemonInput
                        type="number"
                        size="small"
                        min={1}
                        max={30}
                        value={resultsQuery.windowDays}
                        onChange={(windowDays) => {
                            const clamped = clampWindowDays(windowDays)
                            if (clamped !== null) {
                                setResultsQuery({ windowDays: clamped })
                            }
                        }}
                        className="w-16"
                        data-attr="transactional-email-results-window"
                    />
                </ResultsField>
                <ResultsField label="Revenue from">
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
                </ResultsField>
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
