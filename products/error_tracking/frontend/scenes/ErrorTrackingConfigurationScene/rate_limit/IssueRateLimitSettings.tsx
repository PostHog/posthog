import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconRefresh } from '@posthog/icons'
import { LemonSegmentedButton, LemonSelect, LemonTag, Link } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { humanFriendlyLargeNumber } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import { issueRateLimitConfigLogic } from './issueRateLimitConfigLogic'
import { BUCKET_OPTIONS } from './rateLimitConfigLogic'
import { RateLimitHistoryChart } from './RateLimitHistoryChart'
import { formatTotalDuration, RateLimitSimulationChart } from './RateLimitSimulationChart'

export function IssueRateLimitSettings(): JSX.Element {
    const { configLoading } = useValues(issueRateLimitConfigLogic)

    if (configLoading) {
        return (
            <div className="space-y-4">
                <LemonSkeleton className="w-full h-10" />
                <LemonSkeleton className="w-full h-64" />
            </div>
        )
    }

    return (
        <div className="space-y-4">
            <div>
                <div className="flex items-center gap-2 mb-1">
                    <h3 className="font-semibold text-base mb-0">Per-issue rate limit</h3>
                    <LemonTag type="warning" size="small">
                        Experimental
                    </LemonTag>
                </div>
                <p className="text-muted-foreground">
                    This limit applies to each issue per window. Once an issue exceeds the configured rate, further
                    exceptions for it are dropped at ingestion.
                </p>
            </div>

            <Form logic={issueRateLimitConfigLogic} formKey="configForm" enableFormOnSubmit>
                <div className="grid grid-cols-1 md:grid-cols-10 gap-6">
                    <div className="md:col-span-3">
                        <ConfigColumn />
                    </div>
                    <div className="md:col-span-3">
                        <IssuesListColumn />
                    </div>
                    <div className="md:col-span-4">
                        <PreviewColumn />
                    </div>
                </div>
            </Form>
        </div>
    )
}

function ConfigColumn(): JSX.Element {
    const { configFormChanged, isConfigFormSubmitting } = useValues(issueRateLimitConfigLogic)

    return (
        <div className="space-y-3">
            <LemonField name="per_issue_rate_limit_value" label="Maximum exceptions">
                {({ value, onChange }) => (
                    <LemonInput
                        type="number"
                        min={1}
                        value={value ?? undefined}
                        onChange={(v) => onChange(v ?? null)}
                        placeholder="Unlimited"
                        fullWidth
                        data-attr="issue-rate-limit-value"
                    />
                )}
            </LemonField>

            <LemonField name="per_issue_rate_limit_bucket_size_minutes" label="Per">
                {({ value, onChange }) => (
                    <LemonSelect
                        value={value}
                        onChange={onChange}
                        options={BUCKET_OPTIONS.map((o) => ({ label: o.label, value: o.minutes }))}
                        fullWidth
                        data-attr="issue-rate-limit-bucket-size"
                    />
                )}
            </LemonField>

            <p className="text-muted-foreground text-xs">Leave the value empty for no limit.</p>

            <div className="flex justify-start pt-2">
                <LemonButton
                    type="primary"
                    htmlType="submit"
                    disabledReason={!configFormChanged ? 'No changes to save' : undefined}
                    loading={isConfigFormSubmitting}
                >
                    Save
                </LemonButton>
            </div>
        </div>
    )
}

function IssuesListColumn(): JSX.Element {
    const { topIssues, topIssuesLoading, selectedIssueId, configForm } = useValues(issueRateLimitConfigLogic)
    const { selectIssue } = useActions(issueRateLimitConfigLogic)

    const windowLabel = formatTotalDuration(configForm.per_issue_rate_limit_bucket_size_minutes)
    const heading = <div className="text-sm font-medium mb-1">Most active issues — past {windowLabel}</div>

    if (topIssuesLoading) {
        return (
            <div className="space-y-1">
                {heading}
                <LemonSkeleton className="w-full h-80" />
            </div>
        )
    }

    if (topIssues.length === 0) {
        return (
            <div className="space-y-1">
                {heading}
                <div className="border rounded p-4 text-sm text-muted-foreground h-80 flex items-center justify-center text-center">
                    No exceptions captured in the past {windowLabel} yet.
                </div>
            </div>
        )
    }

    return (
        <div className="space-y-1">
            {heading}
            <div className="border rounded divide-y h-80 overflow-y-auto bg-surface-secondary">
                {topIssues.map((issue) => {
                    const isSelected = issue.issue_id === selectedIssueId
                    return (
                        <div
                            key={issue.issue_id}
                            role="button"
                            tabIndex={0}
                            className={`w-full flex items-center gap-3 pl-3 pr-3 py-2 cursor-pointer border-l-2 ${
                                isSelected
                                    ? 'border-l-primary bg-fill-highlight-100'
                                    : 'border-l-transparent hover:bg-fill-highlight-50'
                            }`}
                            onClick={() => selectIssue(issue.issue_id)}
                            onKeyDown={(e) => {
                                if (e.key === 'Enter' || e.key === ' ') {
                                    e.preventDefault()
                                    selectIssue(issue.issue_id)
                                }
                            }}
                            data-attr="issue-rate-limit-row"
                        >
                            <div className="flex-1 min-w-0">
                                <div className="text-sm font-medium truncate">
                                    <Link
                                        subtle
                                        to={urls.errorTrackingIssue(issue.issue_id)}
                                        onClick={(e) => e.stopPropagation()}
                                    >
                                        {issue.name || 'Untitled issue'}
                                    </Link>
                                </div>
                                {issue.description ? (
                                    <div className="text-xs text-secondary truncate">{issue.description}</div>
                                ) : null}
                            </div>
                            <div className="text-right shrink-0">
                                <div className="text-sm font-medium">{humanFriendlyLargeNumber(issue.occurrences)}</div>
                                <div className="text-xs text-muted-foreground">events</div>
                            </div>
                        </div>
                    )
                })}
            </div>
        </div>
    )
}

function PreviewColumn(): JSX.Element {
    const {
        selectedIssue,
        selectedIssueVolume,
        selectedIssueVolumeLoading,
        selectedIssueHistory,
        selectedIssueHistoryLoading,
        chartMode,
        configForm,
        topIssues,
    } = useValues(issueRateLimitConfigLogic)
    const { setChartMode, refreshChart } = useActions(issueRateLimitConfigLogic)

    const limit = configForm.per_issue_rate_limit_value
    const bucketMinutes = configForm.per_issue_rate_limit_bucket_size_minutes
    const chartLoading = chartMode === 'history' ? selectedIssueHistoryLoading : selectedIssueVolumeLoading

    const heading = (
        <div className="text-sm font-medium mb-1 truncate">
            {selectedIssue ? `"${selectedIssue.name || 'Untitled issue'}"` : 'Volume'}
        </div>
    )

    if (topIssues.length === 0) {
        return (
            <div className="space-y-1">
                {heading}
                <div className="border rounded p-4 text-sm text-muted-foreground h-80 flex items-center justify-center text-center">
                    Pick an issue from the list to preview its volume.
                </div>
            </div>
        )
    }

    return (
        <div className="space-y-2">
            {heading}
            <p className="text-muted-foreground text-xs">
                {chartMode === 'simulation'
                    ? "This shows the issue's past traffic to help you choose a rate limit."
                    : "This shows how many of the issue's exceptions were recorded vs dropped based on your rate limits."}
            </p>
            <div className="relative">
                <div className="absolute top-2 left-2 right-2 z-10 flex items-center justify-between gap-2 pointer-events-none">
                    <LemonSegmentedButton
                        className="pointer-events-auto bg-surface-primary rounded"
                        size="xsmall"
                        value={chartMode}
                        onChange={setChartMode}
                        options={[
                            { value: 'simulation', label: 'Simulation' },
                            { value: 'history', label: 'History' },
                        ]}
                    />
                    <div className="pointer-events-auto flex items-center gap-2 bg-surface-primary rounded pl-2">
                        <span className="text-muted-foreground text-xs">Past {formatTotalDuration(bucketMinutes)}</span>
                        <LemonButton
                            size="xsmall"
                            type="secondary"
                            icon={<IconRefresh />}
                            onClick={refreshChart}
                            loading={chartLoading}
                            tooltip="Refresh with the latest data"
                        />
                    </div>
                </div>
                {chartMode === 'simulation' ? (
                    selectedIssueVolumeLoading && selectedIssueVolume.length === 0 ? (
                        <LemonSkeleton className="w-full h-80" />
                    ) : (
                        <RateLimitSimulationChart
                            volume={selectedIssueVolume}
                            rateLimit={limit}
                            bucketMinutes={bucketMinutes}
                        />
                    )
                ) : selectedIssueHistoryLoading && selectedIssueHistory.length === 0 ? (
                    <LemonSkeleton className="w-full h-80" />
                ) : (
                    <RateLimitHistoryChart
                        history={selectedIssueHistory}
                        bucketMinutes={bucketMinutes}
                        emptyMessage="No rate limiting activity recorded yet for this issue. Exceptions dropped by your per-issue limit will appear here."
                    />
                )}
            </div>
        </div>
    )
}
