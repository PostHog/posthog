import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSelect } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { PERFORMANCE_DATE_RANGES, transactionalEmailPerformanceLogic } from './transactionalEmailPerformanceLogic'
import { TransactionalEmailResults } from './TransactionalEmailResults'
import { TransactionalEmailStatsTable } from './TransactionalEmailStatsTable'

export function TransactionalEmailPerformance(): JSX.Element {
    const { days, templateStats, templateStatsLoading, domainStats, domainStatsLoading, statsFailed } = useValues(
        transactionalEmailPerformanceLogic
    )
    const { setDays, loadTemplateStats, loadDomainStats } = useActions(transactionalEmailPerformanceLogic)
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
                        'data-attr': 'transactional-email-performance-retry',
                    }}
                >
                    The numbers couldn't load. Check your connection and try again.
                </LemonBanner>
            )}
            <SceneSection
                title="By email"
                description="Delivered and bounced count against what was sent. Spam reports, opens and clicks count against what was delivered."
                actions={
                    <LemonSelect
                        size="small"
                        value={days}
                        onChange={setDays}
                        options={PERFORMANCE_DATE_RANGES.map((range) => ({ value: range.value, label: range.label }))}
                        data-attr="transactional-email-performance-date-filter"
                    />
                }
            >
                <TransactionalEmailStatsTable
                    rows={templateStats}
                    loading={templateStatsLoading}
                    groupTitle="Email"
                    linkFor={(row) => (row.label ? urls.transactionalTemplate(row.key) : null)}
                    emptyState={emptyState}
                    dataAttr="transactional-email-performance-by-email"
                />
            </SceneSection>
            <SceneDivider />
            <SceneSection title="By sending domain" description="The same counts for each domain the emails came from.">
                <TransactionalEmailStatsTable
                    rows={domainStats}
                    loading={domainStatsLoading}
                    groupTitle="Sending domain"
                    emptyState={emptyState}
                    dataAttr="transactional-email-performance-by-domain"
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
