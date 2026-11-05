import { LemonBanner, LemonButton, LemonSelect, Link, Spinner } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { describeOutcome } from './featureFlagCodeSnippets'
import type { FeatureFlagCodeCleanupApi, FeatureFlagCodeCleanupRunApi } from './generated/api.schemas'

export interface FeatureFlagCodeCleanupPanelProps {
    cleanup: FeatureFlagCodeCleanupApi
    repository: string
    selectedOutcome: string | null
    opening: boolean
    error: string | null
    onSelectOutcome: (outcome: string) => void
    onOpen: () => void
}

// Mirrors the server: a run in progress, or one that opened a pull request, blocks another request.
function blocksNewRequest(run: FeatureFlagCodeCleanupRunApi | null): boolean {
    return !!run && (!run.is_terminal || (run.run_status === 'completed' && !!run.pr_url))
}

function outcomeLabel(outcome: string, suggestedOutcome: string | null): string {
    const { label } = describeOutcome(outcome)
    return outcome === suggestedOutcome ? `${label} (what everyone gets today)` : label
}

export function FeatureFlagCodeCleanupPanel({
    cleanup,
    repository,
    selectedOutcome,
    opening,
    error,
    onSelectOutcome,
    onOpen,
}: FeatureFlagCodeCleanupPanelProps): JSX.Element | null {
    const { run } = cleanup
    const canRequest = cleanup.unavailable_reason === null && !blocksNewRequest(run)

    if (!run && !canRequest) {
        return null
    }

    const taskLink = run?.can_view_task ? (
        <Link to={urls.taskDetail(run.task_id)} data-attr="feature-flag-code-cleanup-task-link">
            View task
        </Link>
    ) : null

    return (
        <div className="flex flex-col gap-2 border-t pt-4">
            <h4 className="m-0">Remove this flag from the code</h4>

            {run && !run.is_terminal ? (
                <div className="flex flex-wrap items-center gap-2">
                    <Spinner />
                    <span>Opening a cleanup pull request in {repository}</span>
                    <span className="text-secondary">You can leave this page and come back.</span>
                    {taskLink}
                </div>
            ) : run?.run_status === 'completed' && run.pr_url ? (
                <LemonBanner
                    type="success"
                    action={{
                        children: 'View pull request',
                        to: run.pr_url,
                        targetBlank: true,
                        'data-attr': 'feature-flag-code-cleanup-pr-link',
                    }}
                >
                    A draft pull request removes this flag's checks. After it merges and deploys, archive the flag.
                </LemonBanner>
            ) : run?.run_status === 'completed' ? (
                <LemonBanner type="info">
                    The agent found no checks of this flag to remove, so it didn't open a pull request. {taskLink}
                </LemonBanner>
            ) : run ? (
                <LemonBanner type="error">
                    {run.run_status === 'cancelled'
                        ? 'The cleanup was canceled.'
                        : (run.error_message ?? "The cleanup pull request couldn't be opened.")}{' '}
                    {taskLink}
                </LemonBanner>
            ) : null}

            {canRequest && (
                <>
                    <p className="m-0 text-secondary max-w-160">
                        This flag is stale. An agent can open a draft pull request in{' '}
                        <span className="font-mono">{repository}</span> that removes these checks and keeps the code for
                        one outcome. It doesn't change the flag.
                    </p>
                    {cleanup.suggested_outcome === null && (
                        <p className="m-0 text-secondary max-w-160">
                            Users get different outcomes from this flag, so choose which code to keep.
                        </p>
                    )}
                    <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm">Keep the code for</span>
                        <LemonSelect
                            size="small"
                            placeholder="Choose an outcome"
                            value={selectedOutcome}
                            onChange={(value) => value && onSelectOutcome(value)}
                            options={cleanup.outcome_options.map((outcome) => ({
                                value: outcome,
                                label: outcomeLabel(outcome, cleanup.suggested_outcome),
                            }))}
                            data-attr="feature-flag-code-cleanup-outcome"
                        />
                        <LemonButton
                            type="primary"
                            size="small"
                            onClick={onOpen}
                            loading={opening}
                            disabledReason={selectedOutcome ? undefined : 'Choose which code to keep'}
                            data-attr="feature-flag-code-cleanup-open"
                        >
                            Open cleanup PR
                        </LemonButton>
                    </div>
                    {error && <LemonBanner type="error">{error}</LemonBanner>}
                </>
            )}
        </div>
    )
}
