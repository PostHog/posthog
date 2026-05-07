import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonSelect, Link } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { humanFriendlyLargeNumber } from 'lib/utils'
import { urls } from 'scenes/urls'

import { issueRateLimitConfigLogic } from './issueRateLimitConfigLogic'
import { BUCKET_OPTIONS } from './rateLimitConfigLogic'
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
                <h3 className="font-semibold text-base mb-1">Per-issue rate limit</h3>
                <p className="text-muted-foreground">
                    This limit applies to each issue individually. Once an issue exceeds the configured rate, further
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

            <p className="text-muted-foreground text-xs">
                Applies to every issue independently. Leave the value empty for no limit.
            </p>

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
    const { topIssues, topIssuesLoading, selectedIssueId } = useValues(issueRateLimitConfigLogic)
    const { selectIssue } = useActions(issueRateLimitConfigLogic)

    const heading = <div className="text-sm font-medium mb-1">Most active issues — past 7 days</div>

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
                    No exceptions captured in the past 7 days yet.
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
    const { selectedIssue, selectedIssueVolume, selectedIssueVolumeLoading, configForm, topIssues } =
        useValues(issueRateLimitConfigLogic)

    const limit = configForm.per_issue_rate_limit_value
    const bucketMinutes = configForm.per_issue_rate_limit_bucket_size_minutes

    const heading = (
        <div className="text-sm font-medium mb-1 truncate">
            {selectedIssue
                ? `Exception volume for "${selectedIssue.name || 'Untitled issue'}" — past ${formatTotalDuration(bucketMinutes)}`
                : 'Volume'}
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

    if (selectedIssueVolumeLoading) {
        return (
            <div className="space-y-1">
                {heading}
                <LemonSkeleton className="w-full h-80" />
            </div>
        )
    }

    return (
        <div className="space-y-1">
            {heading}
            <RateLimitSimulationChart volume={selectedIssueVolume} rateLimit={limit} bucketMinutes={bucketMinutes} />
        </div>
    )
}
