import { IconArrowRight, IconExternal, IconGitBranch, IconGithub } from '@posthog/icons'
import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import type { WizardRunApi, WizardRunArtifactApi, WizardRunGitDiffArtifactApi } from '../generated/api.schemas'
import { formatArtifactSize } from '../wizardRunDisplay'
import { WizardRunDiffStats } from './WizardRunDiffStats'

export function WizardRunDetailsArtifacts({
    run,
    artifacts,
    loading,
    onOpenDiff,
}: {
    run: WizardRunApi
    artifacts: WizardRunArtifactApi[]
    loading: boolean
    onOpenDiff: (artifact: WizardRunGitDiffArtifactApi) => void
}): JSX.Element {
    if (loading) {
        return <LemonSkeleton repeat={2} className="h-12 w-full" />
    }

    if (artifacts.length === 0) {
        return (
            <p className="m-0 text-sm text-muted">
                {run.status === 'created' || run.status === 'running'
                    ? 'Artifacts will appear here when the Wizard produces them.'
                    : 'This run did not produce any artifacts.'}
            </p>
        )
    }

    const pullRequest = artifacts.find((artifact) => artifact.artifact_type === 'pull_request')
    const gitDiff = artifacts.find((artifact) => artifact.artifact_type === 'git_diff')

    return (
        <div className="divide-y divide-primary overflow-hidden rounded border border-primary">
            {pullRequest && (
                <LemonButton
                    type="tertiary"
                    fullWidth
                    to={pullRequest.url}
                    targetBlank
                    hideExternalLinkIcon
                    icon={<IconGithub />}
                    className="h-auto rounded-none px-3 py-3"
                >
                    <span className="flex w-full min-w-0 items-center justify-between gap-3">
                        <span className="flex min-w-0 flex-col items-start gap-1">
                            <span className="font-semibold">Pull request #{pullRequest.number}</span>
                            <span className="flex min-w-0 items-center gap-1 text-xs text-muted">
                                <IconGitBranch className="shrink-0" />
                                <span className="truncate">{pullRequest.base_branch}</span>
                                <IconArrowRight className="shrink-0" />
                                <span className="truncate">{pullRequest.head_branch}</span>
                            </span>
                        </span>
                        <span className="flex shrink-0 items-center gap-2">
                            {gitDiff && (
                                <WizardRunDiffStats additions={gitDiff.additions} removals={gitDiff.removals} />
                            )}
                            <IconExternal className="size-4 text-muted" />
                        </span>
                    </span>
                </LemonButton>
            )}
            {gitDiff && (
                <LemonButton
                    type="tertiary"
                    fullWidth
                    icon={<IconGitBranch />}
                    onClick={() => onOpenDiff(gitDiff)}
                    data-attr="wizard-run-open-git-diff"
                    className="h-auto rounded-none px-3 py-3"
                >
                    <span className="flex w-full min-w-0 items-center justify-between gap-3">
                        <span className="flex min-w-0 flex-col items-start gap-1">
                            <span className="font-semibold">Git diff</span>
                            <span className="text-xs text-muted">{formatArtifactSize(gitDiff.size_bytes)}</span>
                        </span>
                        <WizardRunDiffStats additions={gitDiff.additions} removals={gitDiff.removals} />
                    </span>
                </LemonButton>
            )}
        </div>
    )
}
