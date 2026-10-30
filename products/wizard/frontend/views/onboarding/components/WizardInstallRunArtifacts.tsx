import { IconGitBranch, IconGithub } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import type { WizardRunApi, WizardRunArtifactApi } from '../../../generated/api.schemas'
import { formatArtifactSize } from '../../../lib/wizardRunDisplay'
import type { WizardOnboardingArtifactClickSource } from '../onboardingWizardRunLogic'

export function WizardInstallRunArtifacts({
    run,
    artifacts,
    loading,
    error,
    onArtifactClick,
}: {
    run: WizardRunApi
    artifacts: readonly WizardRunArtifactApi[]
    loading: boolean
    error: string | null
    onArtifactClick?: (artifact: WizardRunArtifactApi, source: WizardOnboardingArtifactClickSource) => void
}): JSX.Element | null {
    if (run.environment !== 'cloud') {
        return null
    }
    if (artifacts.length === 0) {
        if (run.status !== 'completed' || error) {
            return null
        }
        return (
            <p className="mt-3 mb-0 text-xs text-muted">
                {loading ? 'Loading artifacts…' : 'This run did not produce any artifacts.'}
            </p>
        )
    }
    const pullRequest = artifacts.find((artifact) => artifact.artifact_type === 'pull_request')
    return (
        <div className="mt-3 flex flex-wrap items-center gap-3 border-t border-primary pt-2">
            <ul className="m-0 min-w-0 flex-1 list-none space-y-1 p-0">
                {artifacts.map((artifact) => {
                    if (artifact.artifact_type === 'pull_request') {
                        return (
                            <li key={artifact.id}>
                                <LinkPrimitive
                                    to={artifact.url}
                                    target="_blank"
                                    onClick={() => onArtifactClick?.(artifact, 'artifact_list')}
                                    className="flex min-w-0 items-center gap-2 text-xs hover:underline"
                                    data-attr="wizard-install-artifact"
                                >
                                    <IconGithub />
                                    <span className="truncate">{`Pull request #${artifact.number}`}</span>
                                </LinkPrimitive>
                            </li>
                        )
                    }
                    return (
                        <li key={artifact.id}>
                            <span className="flex min-w-0 items-center gap-2 text-xs text-muted">
                                <IconGitBranch />
                                <span className="truncate">{`Git diff (${formatArtifactSize(artifact.size_bytes)})`}</span>
                            </span>
                        </li>
                    )
                })}
            </ul>
            {run.status === 'completed' && pullRequest && (
                <LemonButton
                    type="primary"
                    size="xsmall"
                    to={pullRequest.url}
                    targetBlank
                    onClick={() => onArtifactClick?.(pullRequest, 'review_button')}
                    data-attr="wizard-install-review-pr"
                >
                    Review pull request
                </LemonButton>
            )}
        </div>
    )
}
