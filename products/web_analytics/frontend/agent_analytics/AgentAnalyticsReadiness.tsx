import { useActions, useValues } from 'kea'
import { Field, Form } from 'kea-forms'

import { IconCheck, IconInfo, IconWarning } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCard,
    LemonInput,
    LemonSkeleton,
    LemonTable,
    LemonTableColumns,
    LemonTag,
    Link,
} from '@posthog/lemon-ui'

import { humanFriendlyLargeNumber, percentage } from 'lib/utils/numbers'
import { humanList } from 'lib/utils/strings'
import { tryDecodeURIComponent } from 'lib/utils/url'

import { WebAgentAnalyticsQueryType } from '~/queries/schema/schema-general'

import { DemandRow, LlmsTxtLink, OverviewStats, agentAnalyticsLogic, isDemandCovered } from './agentAnalyticsLogic'
import { AgentAnalyticsSection } from './AgentAnalyticsSection'
import { AgentQueryError } from './AgentQueryError'
import { AgentRequestAnatomy } from './AgentRequestAnatomy'

interface ReadinessCheck {
    status: 'success' | 'warning' | 'neutral'
    statusLabel: string
    label: string
    evidence: string
}

const readinessChecks = (overview: OverviewStats, hasConversionGoal: boolean): ReadinessCheck[] => [
    {
        status: overview.serverRequests > 0 ? 'success' : overview.clientNavigations > 0 ? 'warning' : 'neutral',
        statusLabel:
            overview.serverRequests > 0 ? 'Connected' : overview.clientNavigations > 0 ? 'Partial data' : 'No data',
        label: 'Server request data is available',
        evidence:
            overview.serverRequests > 0
                ? `${humanFriendlyLargeNumber(overview.serverRequests)} server requests were observed in this range`
                : overview.clientNavigations > 0
                  ? 'Client navigations were observed, but response status and format reports need server-side HTTP logs'
                  : 'No agent server requests or client navigations were observed in this range',
    },
    {
        status: overview.llmsTxtFetches > 0 ? 'success' : 'neutral',
        statusLabel: overview.llmsTxtFetches > 0 ? 'Observed' : 'Not observed',
        label: 'Agents can discover llms.txt',
        evidence:
            overview.llmsTxtFetches > 0
                ? `${humanFriendlyLargeNumber(overview.llmsTxtFetches)} successful requests in this range`
                : 'No successful llms.txt requests were observed in this range',
    },
    {
        status: overview.serverRequests === 0 ? 'neutral' : overview.wasted > 0 ? 'warning' : 'success',
        statusLabel: overview.serverRequests === 0 ? 'No data' : overview.wasted > 0 ? 'Needs attention' : 'Ready',
        label: 'Agents avoid repeated format requests',
        evidence:
            overview.serverRequests === 0
                ? 'No agent server requests were observed in this range'
                : overview.wasted > 0
                  ? `${humanFriendlyLargeNumber(overview.wasted)} markdown requests were made near an HTML request for the same client session across ${overview.wastePages} pages`
                  : 'No repeated HTML and markdown request patterns were detected',
    },
    {
        status: hasConversionGoal && overview.convertedClients > 0 ? 'success' : 'neutral',
        statusLabel: !hasConversionGoal
            ? 'Not configured'
            : overview.convertedClients > 0
              ? 'Observed'
              : 'Not observed',
        label: 'Agent conversions are measurable',
        evidence: !hasConversionGoal
            ? 'Select a conversion goal to measure agent conversions'
            : overview.convertedClients > 0
              ? `${humanFriendlyLargeNumber(overview.convertedClients)} agent clients reached the selected conversion goal in this range`
              : 'No agent clients reached the selected conversion goal in this range',
    },
]

const demandColumns = (llmsTxtLinks: Map<string, LlmsTxtLink>, hasInput: boolean): LemonTableColumns<DemandRow> => [
    {
        title: 'Page agents requested',
        key: 'page',
        render: (_, row) => (
            <div className="flex min-w-0 items-baseline gap-1">
                <span className="shrink-0 text-xs text-secondary">{row.host || 'Unknown domain'}</span>
                <span className="font-medium truncate">{tryDecodeURIComponent(row.path)}</span>
            </div>
        ),
    },
    {
        title: 'Requests',
        key: 'demand',
        align: 'right',
        render: (_, row) => humanFriendlyLargeNumber(row.demand),
    },
    {
        title: 'Listed in llms.txt',
        key: 'covered',
        align: 'center',
        render: (_, row) => {
            if (!hasInput) {
                return <span className="text-xs text-secondary">Load to compare</span>
            }
            return isDemandCovered(row, llmsTxtLinks) ? (
                <LemonTag type="success" size="small" icon={<IconCheck />}>
                    Listed
                </LemonTag>
            ) : (
                <LemonTag type="warning" size="small">
                    Missing
                </LemonTag>
            )
        },
    },
]

export const AgentAnalyticsReadiness = (): JSX.Element => {
    const {
        overview,
        overviewLoading,
        overviewError,
        demandRows,
        demandRowsLoading,
        demandRowsError,
        llmsTxtLinks,
        llmsTxtSource,
        isLlmsTxtSourceSubmitting,
        llmsTxtFetchError,
        llmsTxtLoadedUrl,
        conversionGoal,
        resultPaginations,
        demandCoverage,
    } = useValues(agentAnalyticsLogic)
    const { loadOverview, loadDemandRows } = useActions(agentAnalyticsLogic)
    const hasInput = llmsTxtLinks.size > 0
    const { missingPages, totalDemand, listedDemand, observedHosts, hasMatchingHost } = demandCoverage
    const observedHostSummary =
        observedHosts.length > 3
            ? `${observedHosts.slice(0, 3).join(', ')}, and ${observedHosts.length - 3} more`
            : humanList(observedHosts)

    return (
        <div className="flex flex-col gap-6">
            <AgentAnalyticsSection
                title="Readiness checks"
                description="Checks based on agent traffic observed in this project."
            >
                <AgentQueryError
                    error={overviewError}
                    subject="readiness checks"
                    onRetry={loadOverview}
                    loading={overviewLoading}
                >
                    {overview ? (
                        <LemonCard hoverEffect={false} className="divide-y divide-primary overflow-hidden p-0">
                            {readinessChecks(overview, conversionGoal !== null).map((check) => (
                                <div
                                    key={check.label}
                                    className="flex flex-wrap items-start justify-between gap-3 px-4 py-3"
                                >
                                    <div className="flex min-w-0 items-start gap-2">
                                        {check.status === 'success' ? (
                                            <IconCheck className="mt-0.5 shrink-0 text-success" />
                                        ) : check.status === 'warning' ? (
                                            <IconWarning className="mt-0.5 shrink-0 text-warning" />
                                        ) : (
                                            <IconInfo className="mt-0.5 shrink-0 text-secondary" />
                                        )}
                                        <div className="flex min-w-0 flex-col gap-0.5">
                                            <span className="font-medium">{check.label}</span>
                                            <span className="text-xs text-secondary">{check.evidence}</span>
                                        </div>
                                    </div>
                                    <LemonTag type={check.status === 'neutral' ? 'muted' : check.status} size="small">
                                        {check.statusLabel}
                                    </LemonTag>
                                </div>
                            ))}
                        </LemonCard>
                    ) : (
                        <LemonCard hoverEffect={false} className="divide-y divide-primary overflow-hidden p-0">
                            {[0, 1, 2, 3].map((index) => (
                                <div key={index} className="flex items-center gap-3 px-4 py-3">
                                    <LemonSkeleton.Circle className="size-4" />
                                    <div className="flex flex-1 flex-col gap-1.5">
                                        <LemonSkeleton className="h-4 w-64 max-w-full" />
                                        <LemonSkeleton className="h-3 w-96 max-w-full" />
                                    </div>
                                    <LemonSkeleton className="h-5 w-20" />
                                </div>
                            ))}
                        </LemonCard>
                    )}
                </AgentQueryError>
            </AgentAnalyticsSection>

            <AgentRequestAnatomy />

            <AgentAnalyticsSection
                title="llms.txt coverage"
                description={
                    <>
                        Load your <Link to="https://llmstxt.org/">llms.txt</Link> file to compare its pages with
                        successful agent requests. Absolute links match their origin and case-sensitive path, with an
                        appended <code>.md</code> treated as the same page. Relative links use the loaded file URL.
                    </>
                }
                right={
                    hasInput ? (
                        <div className="flex items-center gap-1">
                            <LemonTag type="success" size="small">
                                {totalDemand > 0 ? percentage(listedDemand / totalDemand, 0) : '0%'} of requests on this
                                page listed
                            </LemonTag>
                            <LemonTag type="warning" size="small">
                                {humanFriendlyLargeNumber(missingPages)} of{' '}
                                {humanFriendlyLargeNumber(demandRows.length)} pages missing on this page
                            </LemonTag>
                        </div>
                    ) : undefined
                }
            >
                <Form logic={agentAnalyticsLogic} formKey="llmsTxtSource" enableFormOnSubmit className="@container">
                    <div className="flex flex-col gap-2 @md:flex-row @md:items-end">
                        <div className="min-w-0 flex-1">
                            <Field
                                name="url"
                                label="llms.txt URL"
                                help="PostHog loads up to 1 MB from a public HTTP or HTTPS URL. The file is used for this comparison and is not saved."
                            >
                                <LemonInput
                                    type="url"
                                    inputMode="url"
                                    placeholder="https://example.com/llms.txt"
                                    maxLength={2048}
                                    fullWidth
                                />
                            </Field>
                        </div>
                        <LemonButton
                            type="secondary"
                            htmlType="submit"
                            loading={isLlmsTxtSourceSubmitting}
                            disabledReason={!llmsTxtSource.url.trim() ? 'Enter a URL to load' : undefined}
                            data-attr="agent-analytics-load-llms-txt"
                        >
                            Load file
                        </LemonButton>
                    </div>
                </Form>
                {llmsTxtFetchError ? <LemonBanner type="error">{llmsTxtFetchError}</LemonBanner> : null}
                {llmsTxtLoadedUrl ? (
                    <LemonBanner type="success">
                        Loaded from <span className="break-all font-medium">{llmsTxtLoadedUrl}</span>.
                    </LemonBanner>
                ) : null}
                {hasInput && demandRows.length > 0 && observedHosts.length > 0 && !hasMatchingHost ? (
                    <LemonBanner type="warning">
                        None of the links in this file match the observed{' '}
                        {observedHosts.length === 1 ? 'domain' : 'domains'}{' '}
                        <span className="font-medium">{observedHostSummary}</span>. Select a matching domain or load its
                        llms.txt file.
                    </LemonBanner>
                ) : null}
                <AgentQueryError
                    error={demandRowsError}
                    subject="requested pages"
                    onRetry={loadDemandRows}
                    loading={demandRowsLoading}
                >
                    <LemonTable
                        columns={demandColumns(llmsTxtLinks, hasInput)}
                        dataSource={demandRows}
                        loading={demandRowsLoading}
                        size="small"
                        nouns={['page', 'pages']}
                        pagination={resultPaginations[WebAgentAnalyticsQueryType.Demand]}
                        emptyState="No successful agent page requests were found in this range."
                    />
                </AgentQueryError>
            </AgentAnalyticsSection>
        </div>
    )
}
