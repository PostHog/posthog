import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSelect } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { METRICS_DATE_RANGES, transactionalEmailMetricsLogic } from './transactionalEmailMetricsLogic'
import { TransactionalEmailResults } from './TransactionalEmailResults'
import { TransactionalEmailStatsTable } from './TransactionalEmailStatsTable'

export function TransactionalEmailMetrics(): JSX.Element {
    const { hours, templateStats, templateStatsLoading, domainStats, domainStatsLoading, statsFailed } =
        useValues(transactionalEmailMetricsLogic)
    const { setHours, loadTemplateStats, loadDomainStats } = useActions(transactionalEmailMetricsLogic)
    const emptyState = statsFailed ? "The numbers couldn't load" : 'No transactional emails were sent in this period'

    return (
        <div className="flex flex-col gap-4">
            {statsFailed && !templateStatsLoading && !domainStatsLoading && (
                <LemonBanner
                    type="error"
                    action={{
                        children: 'Try again',
                        onClick: () => {
                            loadTemplateStats()
                            loadDomainStats()
                        },
                        'data-attr': 'transactional-email-metrics-retry',
                    }}
                >
                    The numbers couldn't load. Check your connection and try again.
                </LemonBanner>
            )}
            <SceneSection
                title="By email"
                description="Delivered and bounced are shares of what was sent. Marked as spam, opened and clicked are shares of what was delivered."
                actions={
                    <LemonSelect
                        size="small"
                        value={hours}
                        onChange={setHours}
                        options={METRICS_DATE_RANGES.map((range) => ({ value: range.value, label: range.label }))}
                        data-attr="transactional-email-metrics-date-filter"
                    />
                }
            >
                <TransactionalEmailStatsTable
                    rows={templateStats}
                    loading={templateStatsLoading}
                    groupTitle="Email"
                    linkFor={(row) => (row.label ? urls.transactionalTemplate(row.key) : null)}
                    emptyState={emptyState}
                    dataAttr="transactional-email-metrics-by-email"
                />
            </SceneSection>
            <SceneDivider />
            <SceneSection title="By sending domain" description="The same counts for each domain the emails came from.">
                <TransactionalEmailStatsTable
                    rows={domainStats}
                    loading={domainStatsLoading}
                    groupTitle="Sending domain"
                    emptyState={emptyState}
                    dataAttr="transactional-email-metrics-by-domain"
                />
            </SceneSection>
            <SceneDivider />
            <SceneSection
                title="What happened after"
                description="Of the people an email was sent to, how many did an event afterwards, and the revenue that came with it."
            >
                <TransactionalEmailResults />
            </SceneSection>
        </div>
    )
}
