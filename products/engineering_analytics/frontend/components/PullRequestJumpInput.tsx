import { useActions, useValues } from 'kea'

import { IconPullRequest } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { type PullRequestJumpFailure, engineeringAnalyticsLogic } from '../scenes/engineeringAnalyticsLogic'

const FAILURE_MESSAGE: Record<PullRequestJumpFailure, string> = {
    invalid: 'Enter a GitHub pull request link or number.',
    needs_repository: 'Select a repository or paste the full link.',
}

/** Opens one pull request in the CI explorer from a link or a number, whether or not the list holds it. */
export function PullRequestJumpInput(): JSX.Element {
    const { pullRequestJumpText, pullRequestJumpFailure, githubSourcesLoading } = useValues(engineeringAnalyticsLogic)
    const { setPullRequestJumpText, submitPullRequestJump } = useActions(engineeringAnalyticsLogic)

    return (
        <LemonField.Pure error={pullRequestJumpFailure && FAILURE_MESSAGE[pullRequestJumpFailure]} className="gap-1">
            <div className="flex flex-wrap items-center gap-2">
                <LemonInput
                    prefix={<IconPullRequest />}
                    placeholder="Pull request link or number"
                    aria-label="Pull request link or number"
                    value={pullRequestJumpText}
                    onChange={setPullRequestJumpText}
                    onPressEnter={() => submitPullRequestJump()}
                    status={pullRequestJumpFailure ? 'danger' : 'default'}
                    className="w-64"
                    data-attr="engineering-analytics-pull-request-jump-input"
                />
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={() => submitPullRequestJump()}
                    disabledReason={githubSourcesLoading ? 'Loading repositories' : undefined}
                    data-attr="engineering-analytics-pull-request-jump-submit"
                >
                    View in CI explorer
                </LemonButton>
            </div>
        </LemonField.Pure>
    )
}
