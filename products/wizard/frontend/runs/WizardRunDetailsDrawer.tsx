import { IconArrowLeft, IconCopy, IconFolder, IconGithub, IconRefresh, IconStopFilled } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDrawer, LemonSkeleton } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { TZLabel } from 'lib/components/TZLabel'

import type { WizardRunApi, WizardRunArtifactApi, WizardRunGitDiffArtifactApi } from '../generated/api.schemas'
import {
    WIZARD_LOCAL_RUNS_VISIBLE,
    wizardGithubRepositoryUrl,
    wizardRunCanCancel,
    wizardRunDiffCanRender,
    wizardRunIsActive,
    wizardRunTerminalLabel,
    wizardWorkspaceLabel,
} from '../wizardRunDisplay'
import { WizardRunDetailsArtifacts } from './WizardRunDetailsArtifacts'
import { WizardRunDiffStats } from './WizardRunDiffStats'
import { WizardRunDiffViewer } from './WizardRunDiffViewer'
import { WizardRunEnvironmentTag } from './WizardRunEnvironmentTag'
import { WizardRunProgress } from './WizardRunProgress'
import { WizardRunStatusTag } from './WizardRunStatusTag'

export function WizardRunDetailsDrawer({
    run,
    artifacts,
    artifactsLoading,
    currentUserId,
    refreshing,
    cancelling,
    diffArtifactId,
    diffContent,
    diffError,
    diffLoading,
    onClose,
    onCloseDiff,
    onOpenDiff,
    onRefresh,
    onCopyRunId,
    onCancel,
    onRunAgain,
}: {
    run: WizardRunApi | null
    artifacts: WizardRunArtifactApi[]
    artifactsLoading: boolean
    currentUserId: number | null
    refreshing: boolean
    cancelling: boolean
    diffArtifactId: string | null
    diffContent: string | null
    diffError: string | null
    diffLoading: boolean
    onClose: () => void
    onCloseDiff: () => void
    onOpenDiff: (artifact: WizardRunGitDiffArtifactApi) => void
    onRefresh: () => void
    onCopyRunId: (runId: string) => void
    onCancel: (run: WizardRunApi) => void
    onRunAgain: (run: WizardRunApi) => void
}): JSX.Element {
    const pullRequest = artifacts.find((artifact) => artifact.artifact_type === 'pull_request')
    const gitDiff = artifacts.find((artifact) => artifact.artifact_type === 'git_diff')
    const selectedDiff = gitDiff?.id === diffArtifactId ? gitDiff : null

    return (
        <LemonDrawer
            isOpen={!!run}
            onClose={onClose}
            width={selectedDiff ? 960 : 460}
            overlayTransparent
            title={
                run ? (
                    <div className="flex w-full items-center justify-between gap-2 pr-8">
                        <span>{run.program.name}</span>
                        <WizardRunStatusTag status={run.status} />
                    </div>
                ) : (
                    'Wizard run'
                )
            }
            footer={
                run ? (
                    <div className="flex w-full items-center justify-between gap-2">
                        <LemonButton icon={<IconCopy />} onClick={() => onCopyRunId(run.id)}>
                            Copy run ID
                        </LemonButton>

                        {pullRequest ? (
                            <LemonButton type="primary" to={pullRequest.url} targetBlank>
                                Open pull request
                            </LemonButton>
                        ) : wizardRunCanCancel(run, currentUserId) ? (
                            <LemonButton
                                status="danger"
                                icon={<IconStopFilled />}
                                onClick={() => onCancel(run)}
                                loading={cancelling}
                            >
                                Cancel run
                            </LemonButton>
                        ) : run.status === 'failed' && (WIZARD_LOCAL_RUNS_VISIBLE || run.environment === 'cloud') ? (
                            <LemonButton type="primary" onClick={() => onRunAgain(run)}>
                                Run again
                            </LemonButton>
                        ) : null}
                    </div>
                ) : null
            }
        >
            {run && selectedDiff ? (
                <div className="flex min-w-0 flex-col gap-4">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                        <LemonButton
                            icon={<IconArrowLeft />}
                            onClick={onCloseDiff}
                            data-attr="wizard-run-close-git-diff"
                        >
                            Run details
                        </LemonButton>
                        <WizardRunDiffStats additions={selectedDiff.additions} removals={selectedDiff.removals} />
                    </div>
                    {!wizardRunDiffCanRender(selectedDiff.size_bytes) ? (
                        <WizardRunDiffViewer
                            diff=""
                            contentHash={selectedDiff.content_hash}
                            sizeBytes={selectedDiff.size_bytes}
                            pullRequestUrl={pullRequest?.url ?? null}
                        />
                    ) : diffLoading ? (
                        <LemonSkeleton repeat={8} className="h-6 w-full" />
                    ) : diffError ? (
                        <LemonBanner
                            type="error"
                            action={{ children: 'Try again', onClick: () => onOpenDiff(selectedDiff) }}
                        >
                            {diffError}
                        </LemonBanner>
                    ) : diffContent !== null ? (
                        <WizardRunDiffViewer
                            diff={diffContent}
                            contentHash={selectedDiff.content_hash}
                            sizeBytes={selectedDiff.size_bytes}
                            pullRequestUrl={pullRequest?.url ?? null}
                        />
                    ) : (
                        <LemonBanner
                            type="error"
                            action={{ children: 'Try again', onClick: () => onOpenDiff(selectedDiff) }}
                        >
                            Couldn't load this diff. Try again.
                        </LemonBanner>
                    )}
                </div>
            ) : run ? (
                <div className="space-y-5">
                    <dl className="space-y-3 text-sm">
                        <div className="grid grid-cols-[120px_1fr] items-center gap-3">
                            <dt className="text-xs font-semibold uppercase text-muted">Workspace</dt>
                            <dd className="m-0 min-w-0">
                                {run.workspace.type === 'git_repository' ? (
                                    <LemonButton
                                        size="small"
                                        type="tertiary"
                                        icon={<IconGithub />}
                                        to={wizardGithubRepositoryUrl(run.workspace.repository)}
                                        targetBlank
                                        className="w-fit max-w-full"
                                    >
                                        {run.workspace.repository}
                                    </LemonButton>
                                ) : (
                                    <span className="inline-flex items-center gap-1 px-2 py-1 text-sm font-medium">
                                        <IconFolder />
                                        {wizardWorkspaceLabel(run)}
                                    </span>
                                )}
                            </dd>
                        </div>
                        <div className="grid grid-cols-[120px_1fr] items-center gap-3">
                            <dt className="text-xs font-semibold uppercase text-muted">Environment</dt>
                            <dd className="m-0">
                                <WizardRunEnvironmentTag environment={run.environment} />
                            </dd>
                        </div>
                        <div className="grid grid-cols-[120px_1fr] items-center gap-3">
                            <dt className="text-xs font-semibold uppercase text-muted">Started</dt>
                            <dd className="m-0">
                                {run.started_at ? (
                                    <TZLabel time={run.started_at} />
                                ) : (
                                    <span className="text-muted">Not started</span>
                                )}
                            </dd>
                        </div>
                        <div className="grid grid-cols-[120px_1fr] items-center gap-3">
                            <dt className="text-xs font-semibold uppercase text-muted">Run ID</dt>
                            <dd className="m-0 font-mono text-xs">
                                <CopyToClipboardInline
                                    explicitValue={run.id}
                                >{`${run.id.slice(0, 8)}…`}</CopyToClipboardInline>
                            </dd>
                        </div>
                    </dl>

                    <section>
                        <div className="mb-3 flex items-center justify-between">
                            <h4 className="m-0">Artifacts</h4>
                            {wizardRunIsActive(run) && <span className="text-xs text-muted">Pending</span>}
                        </div>
                        <WizardRunDetailsArtifacts
                            run={run}
                            artifacts={artifacts}
                            loading={artifactsLoading}
                            onOpenDiff={onOpenDiff}
                        />
                    </section>

                    <section>
                        <h4 className="mb-4">Run progress</h4>
                        <WizardRunProgress run={run} />
                        <div className="mt-4 flex items-center justify-between text-xs text-muted">
                            <span>
                                {wizardRunIsActive(run) ? (
                                    'Updates automatically.'
                                ) : run.finished_at ? (
                                    <>
                                        {wizardRunTerminalLabel(run.status)} <TZLabel time={run.finished_at} />.
                                    </>
                                ) : (
                                    `${wizardRunTerminalLabel(run.status)}.`
                                )}
                            </span>
                            {run.status === 'failed' && (WIZARD_LOCAL_RUNS_VISIBLE || run.environment === 'cloud') ? (
                                <LemonButton size="small" onClick={() => onRunAgain(run)}>
                                    Run again
                                </LemonButton>
                            ) : wizardRunIsActive(run) ? (
                                <LemonButton
                                    size="small"
                                    icon={<IconRefresh />}
                                    onClick={onRefresh}
                                    loading={refreshing}
                                >
                                    Refresh
                                </LemonButton>
                            ) : null}
                        </div>
                    </section>
                </div>
            ) : null}
        </LemonDrawer>
    )
}
