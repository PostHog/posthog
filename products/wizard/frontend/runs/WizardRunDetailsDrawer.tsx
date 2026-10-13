import { Suspense } from 'react'

import { IconArrowLeft, IconCopy, IconFolder, IconGithub, IconRefresh, IconStopFilled } from '@posthog/icons'
import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Item,
    ItemContent,
    ItemDescription,
    Skeleton,
} from '@posthog/quill-primitives'

import { TZLabel } from 'lib/components/TZLabel'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { lazyWithRetry } from 'lib/utils/retryImport'

import type {
    WizardRunApi,
    WizardRunArtifactApi,
    WizardRunGitDiffArtifactApi,
    WizardRunTaskApi,
} from '../generated/api.schemas'
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
import { WizardRunEnvironmentTag } from './WizardRunEnvironmentTag'
import { WizardRunProgress } from './WizardRunProgress'
import { WizardRunStatusTag } from './WizardRunStatusTag'

const WizardRunDiffViewer = lazyWithRetry(() =>
    import('./WizardRunDiffViewer').then((module) => ({ default: module.WizardRunDiffViewer }))
)

function LoadingRows(): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            {Array.from({ length: 8 }, (_, index) => (
                <Skeleton key={index} className="h-6 w-full" />
            ))}
        </div>
    )
}

function RetryItem({
    children,
    onRetry,
    tone = 'destructive',
}: {
    children: string
    onRetry: () => void
    tone?: 'warning' | 'destructive'
}): JSX.Element {
    return (
        <Item tone={tone} variant="outline">
            <ItemContent>
                <ItemDescription>{children}</ItemDescription>
                <Button variant="outline" size="sm" onClick={onRetry}>
                    Try again
                </Button>
            </ItemContent>
        </Item>
    )
}

export function WizardRunDetailsDrawer({
    run,
    tasks = [],
    artifacts,
    artifactsError,
    artifactsLoading,
    currentUserId,
    detailsError,
    refreshing,
    cancelling,
    diffArtifactId,
    diffContent,
    diffError,
    diffLoading,
    onClose,
    onCloseDiff,
    onOpenDiff,
    onArtifactClick,
    onRefresh,
    onCopyRunId,
    onCancel,
    onRunAgain,
}: {
    run: WizardRunApi | null
    tasks?: readonly WizardRunTaskApi[]
    artifacts: WizardRunArtifactApi[]
    artifactsError: string | null
    artifactsLoading: boolean
    currentUserId: number | null
    detailsError: string | null
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
    onArtifactClick: (artifact: WizardRunArtifactApi, source: 'button' | 'artifacts_section') => void
    onCopyRunId: (runId: string, location: 'bottom_button' | 'run_id_label') => void
    onCancel: (run: WizardRunApi) => void
    onRunAgain?: (run: WizardRunApi) => void
}): JSX.Element {
    const pullRequest = artifacts.find((artifact) => artifact.artifact_type === 'pull_request')
    const gitDiff = artifacts.find((artifact) => artifact.artifact_type === 'git_diff')
    const selectedDiff = gitDiff?.id === diffArtifactId ? gitDiff : null

    return (
        <Dialog open={!!run} onOpenChange={(open) => !open && onClose()}>
            <DialogContent size={selectedDiff ? 'wide' : undefined} className={selectedDiff ? 'max-w-6xl' : 'max-w-xl'}>
                <DialogHeader className="pr-8">
                    <DialogTitle className="flex items-center justify-between gap-2">
                        <span>{run?.program.name ?? 'Wizard run'}</span>
                        {run && <WizardRunStatusTag status={run.status} />}
                    </DialogTitle>
                </DialogHeader>

                {run && (
                    <>
                        <DialogBody>
                            {selectedDiff ? (
                                <div className="flex min-w-0 flex-col gap-4">
                                    <div className="flex flex-wrap items-center justify-between gap-3">
                                        <Button
                                            variant="outline"
                                            onClick={onCloseDiff}
                                            data-attr="wizard-run-close-git-diff"
                                        >
                                            <IconArrowLeft />
                                            Run details
                                        </Button>
                                        <WizardRunDiffStats
                                            additions={selectedDiff.additions}
                                            removals={selectedDiff.removals}
                                        />
                                    </div>
                                    <Suspense fallback={<LoadingRows />}>
                                        {!wizardRunDiffCanRender(selectedDiff.size_bytes) ? (
                                            <WizardRunDiffViewer
                                                diff=""
                                                contentHash={selectedDiff.content_hash}
                                                sizeBytes={selectedDiff.size_bytes}
                                                pullRequestUrl={pullRequest?.url ?? null}
                                            />
                                        ) : diffLoading ? (
                                            <LoadingRows />
                                        ) : diffError ? (
                                            <RetryItem onRetry={() => onOpenDiff(selectedDiff)}>{diffError}</RetryItem>
                                        ) : diffContent !== null ? (
                                            <WizardRunDiffViewer
                                                diff={diffContent}
                                                contentHash={selectedDiff.content_hash}
                                                sizeBytes={selectedDiff.size_bytes}
                                                pullRequestUrl={pullRequest?.url ?? null}
                                            />
                                        ) : (
                                            <RetryItem onRetry={() => onOpenDiff(selectedDiff)}>
                                                Couldn't load this diff. Try again.
                                            </RetryItem>
                                        )}
                                    </Suspense>
                                </div>
                            ) : (
                                <div className="space-y-5">
                                    <dl className="space-y-3 text-sm">
                                        <div className="grid grid-cols-[120px_1fr] items-center gap-3">
                                            <dt className="text-xs font-semibold uppercase text-muted">Workspace</dt>
                                            <dd className="m-0 min-w-0">
                                                {run.workspace.type === 'git_repository' ? (
                                                    <Button
                                                        size="sm"
                                                        variant="link"
                                                        render={
                                                            <LinkPrimitive
                                                                to={wizardGithubRepositoryUrl(run.workspace.repository)}
                                                                target="_blank"
                                                            />
                                                        }
                                                        className="w-fit max-w-full"
                                                    >
                                                        <IconGithub />
                                                        {run.workspace.repository}
                                                    </Button>
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
                                                <Button
                                                    variant="link-muted"
                                                    size="sm"
                                                    onClick={() => onCopyRunId(run.id, 'run_id_label')}
                                                >
                                                    {`${run.id.slice(0, 8)}…`}
                                                    <IconCopy />
                                                </Button>
                                            </dd>
                                        </div>
                                    </dl>

                                    <section>
                                        <div className="mb-3 flex items-center justify-between">
                                            <h4 className="m-0">Artifacts</h4>
                                            {wizardRunIsActive(run) && (
                                                <span className="text-xs text-muted">Pending</span>
                                            )}
                                        </div>
                                        {detailsError && (
                                            <div className="mb-3">
                                                <RetryItem tone="warning" onRetry={onRefresh}>
                                                    {detailsError}
                                                </RetryItem>
                                            </div>
                                        )}
                                        <WizardRunDetailsArtifacts
                                            run={run}
                                            artifacts={artifacts}
                                            error={artifactsError}
                                            loading={artifactsLoading}
                                            onOpenDiff={onOpenDiff}
                                            onArtifactClick={onArtifactClick}
                                            onRetry={onRefresh}
                                        />
                                    </section>

                                    <section>
                                        <h4 className="mb-4">Run progress</h4>
                                        <WizardRunProgress run={run} tasks={tasks} />
                                        <div className="mt-4 flex items-center justify-between text-xs text-muted">
                                            <span>
                                                {wizardRunIsActive(run) ? (
                                                    run.environment === 'local' ? (
                                                        'Stop this run in the terminal where the Wizard is running.'
                                                    ) : (
                                                        'Updates automatically.'
                                                    )
                                                ) : run.finished_at ? (
                                                    <>
                                                        {wizardRunTerminalLabel(run.status)}{' '}
                                                        <TZLabel time={run.finished_at} />.
                                                    </>
                                                ) : (
                                                    `${wizardRunTerminalLabel(run.status)}.`
                                                )}
                                            </span>
                                            {onRunAgain &&
                                            run.status === 'failed' &&
                                            (WIZARD_LOCAL_RUNS_VISIBLE || run.environment === 'cloud') ? (
                                                <Button size="sm" onClick={() => onRunAgain?.(run)}>
                                                    Run again
                                                </Button>
                                            ) : wizardRunIsActive(run) ? (
                                                <Button size="sm" onClick={onRefresh} loading={refreshing}>
                                                    <IconRefresh /> Refresh
                                                </Button>
                                            ) : null}
                                        </div>
                                    </section>
                                </div>
                            )}
                        </DialogBody>
                        <DialogFooter className="flex-row justify-between">
                            <Button variant="outline" onClick={() => onCopyRunId(run.id, 'bottom_button')}>
                                <IconCopy /> Copy run ID
                            </Button>
                            {pullRequest ? (
                                <Button
                                    variant="primary"
                                    render={<LinkPrimitive to={pullRequest.url} target="_blank" />}
                                    onClick={() => onArtifactClick(pullRequest, 'button')}
                                >
                                    Open pull request
                                </Button>
                            ) : wizardRunCanCancel(run, currentUserId) ? (
                                <Button variant="destructive" onClick={() => onCancel(run)} loading={cancelling}>
                                    <IconStopFilled /> Cancel run
                                </Button>
                            ) : onRunAgain &&
                              run.status === 'failed' &&
                              (WIZARD_LOCAL_RUNS_VISIBLE || run.environment === 'cloud') ? (
                                <Button variant="primary" onClick={() => onRunAgain?.(run)}>
                                    Run again
                                </Button>
                            ) : null}
                        </DialogFooter>
                    </>
                )}
            </DialogContent>
        </Dialog>
    )
}
