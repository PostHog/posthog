import { useActions, useValues } from 'kea'

import { IconCopy, IconPause, IconPencil, IconPlay, IconRefresh, IconTrash } from '@posthog/icons'
import {
    AlertDialog,
    AlertDialogClose,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    Badge,
    Button,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    Item,
    ItemContent,
    ItemGroup,
    Skeleton,
    Text,
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
} from '@posthog/quill'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { SpaceSettingsSection } from '../SpaceSettingsSection'
import { SpaceLoopConfiguration } from './SpaceLoopConfiguration'
import { spaceLoopName } from './spaceLoopMapping'
import { SpaceLoopRunRow } from './SpaceLoopRunRow'
import { SPACE_LOOP_RUNS_LIMIT } from './spaceLoopsApi'
import { SpaceLoopSceneLogicProps, spaceLoopSceneLogic } from './spaceLoopSceneLogic'

export const scene: SceneExport<SpaceLoopSceneLogicProps> = {
    component: SpaceLoopScene,
    logic: spaceLoopSceneLogic,
    paramsToProps: ({ params: { id, loopId } }) => ({ id, loopId }),
}

export function SpaceLoopScene({ id, loopId }: SpaceLoopSceneLogicProps): JSX.Element {
    const railNavEnabled = useFeatureFlag('TODAY_RAIL_NAV')
    const loopsEnabled = useFeatureFlag('LOOPS')
    const logic = spaceLoopSceneLogic({ id, loopId })
    const {
        loop,
        loopLoading,
        loopMissing,
        loopUnavailable,
        runs,
        runsLoading,
        savingEnabled,
        runningNow,
        deleting,
        deleteOpen,
        spaceName,
        backend,
        stopRunTarget,
        stoppingRun,
        creator,
    } = useValues(logic)
    const { loadLoop, loadRuns, setEnabled, runNow, copyLink, deleteLoop, setDeleteOpen, setStopRunTarget, stopRun } =
        useActions(logic)

    if (!railNavEnabled || !loopsEnabled || loopMissing) {
        return <NotFound object="loop" />
    }

    const name = loop ? spaceLoopName(loop) : null
    return (
        <TooltipProvider>
            <SceneContent>
                <SceneTitleSection
                    name={name}
                    description={loop?.description || null}
                    isLoading={loopLoading && !loop}
                    resourceType={{ type: 'task' }}
                    forceBackTo={{
                        key: [Scene.TaskSpace, `${id}/loops`],
                        name: `Loops in ${spaceName}`,
                        path: urls.taskSpaceLoops(id),
                    }}
                    nameSuffix={
                        loop ? (
                            <span className="flex shrink-0 items-center gap-1">
                                <Badge variant={loop.status.variant}>{loop.status.label}</Badge>
                                {!loop.foreign && backend && !backend.workflowBacked && (
                                    <Badge>{loop.visibility === 'team' ? 'Team' : 'Personal'}</Badge>
                                )}
                            </span>
                        ) : null
                    }
                    actions={
                        loop ? (
                            <div className="flex flex-wrap items-center gap-1">
                                {/* Resuming an archived workflow would make it active again instead of restoring it. */}
                                {!loop.archived && (
                                    <Button
                                        size="sm"
                                        variant="outline"
                                        loading={savingEnabled}
                                        onClick={() => setEnabled(!loop.enabled)}
                                        data-attr="today-space-loop-toggle"
                                    >
                                        {loop.enabled ? <IconPause /> : <IconPlay />}
                                        <span>{loop.enabled ? 'Pause' : 'Resume'}</span>
                                    </Button>
                                )}
                                {loop.canRunNow && loop.enabled && (
                                    <Button
                                        size="sm"
                                        variant="outline"
                                        loading={runningNow}
                                        onClick={runNow}
                                        data-attr="today-space-loop-run-now"
                                    >
                                        <IconPlay />
                                        Run now
                                    </Button>
                                )}
                                <Button
                                    size="sm"
                                    variant="outline"
                                    onClick={copyLink}
                                    data-attr="today-space-loop-copy-link"
                                >
                                    <IconCopy />
                                    Copy link
                                </Button>
                                {!loop.archived && (
                                    <Tooltip disabled={!loop.foreign}>
                                        <TooltipTrigger
                                            render={
                                                <Button
                                                    size="sm"
                                                    variant="outline"
                                                    disabled={loop.foreign}
                                                    render={
                                                        loop.foreign ? undefined : (
                                                            <LinkPrimitive to={urls.taskSpaceLoopEdit(id, loop.id)} />
                                                        )
                                                    }
                                                    data-attr="today-space-loop-edit"
                                                />
                                            }
                                        >
                                            <IconPencil />
                                            Edit
                                        </TooltipTrigger>
                                        <TooltipContent>
                                            Change this loop in Workflows. It was changed there.
                                        </TooltipContent>
                                    </Tooltip>
                                )}
                                <Button
                                    size="sm"
                                    variant="destructive-outline"
                                    onClick={() => setDeleteOpen(true)}
                                    data-attr="today-space-loop-delete"
                                >
                                    <IconTrash />
                                    Delete
                                </Button>
                            </div>
                        ) : undefined
                    }
                />
                <div className="flex w-full max-w-200 flex-col gap-7 pb-8" data-quill>
                    {loop ? (
                        <>
                            {loop.pausedReason && (
                                <Text size="sm" variant="destructive">
                                    {loop.pausedReason}
                                </Text>
                            )}
                            {loop.foreign && (
                                <Text size="sm" variant="muted">
                                    This loop was changed in the workflow editor, so this page shows only part of it.
                                    Change it in{' '}
                                    <LinkPrimitive to={urls.workflow(loop.id, 'workflow')}>Workflows</LinkPrimitive>.
                                </Text>
                            )}
                            {loop.archived && (
                                <Text size="sm" variant="muted">
                                    This loop is archived in Workflows. Restore it there to run it again.
                                </Text>
                            )}
                            <SpaceLoopConfiguration loop={loop} creator={creator} />
                            <SpaceSettingsSection label="Instructions" description="What the agent does on each run.">
                                <ItemGroup combined>
                                    <Item variant="outline" size="sm" className="max-h-96 overflow-y-auto">
                                        <ItemContent>
                                            <Text size="xs" className="whitespace-pre-wrap">
                                                {loop.instructions || 'No instructions'}
                                            </Text>
                                        </ItemContent>
                                    </Item>
                                </ItemGroup>
                            </SpaceSettingsSection>
                            <SpaceSettingsSection
                                label="Run history"
                                description={`The ${SPACE_LOOP_RUNS_LIMIT} most recent runs. Each run is a session in this space.`}
                                action={
                                    <Button
                                        size="sm"
                                        variant="outline"
                                        loading={runsLoading}
                                        onClick={() => loadRuns()}
                                        data-attr="today-space-loop-runs-refresh"
                                    >
                                        <IconRefresh />
                                        Refresh
                                    </Button>
                                }
                            >
                                {runsLoading && !runs ? (
                                    <Skeleton className="h-16 w-full" />
                                ) : !runs?.length ? (
                                    <Empty className="border border-dashed py-8">
                                        <EmptyHeader>
                                            <EmptyTitle>No runs yet</EmptyTitle>
                                            <EmptyDescription>
                                                {loop.canRunNow && loop.enabled
                                                    ? 'Runs show here once this loop fires. Start one with Run now, or wait for its next trigger.'
                                                    : 'Runs show here once this loop fires.'}
                                            </EmptyDescription>
                                        </EmptyHeader>
                                    </Empty>
                                ) : (
                                    <ItemGroup combined>
                                        {runs.map((run) => (
                                            <SpaceLoopRunRow
                                                key={run.id}
                                                run={run}
                                                onStop={() => setStopRunTarget(run)}
                                            />
                                        ))}
                                    </ItemGroup>
                                )}
                            </SpaceSettingsSection>
                        </>
                    ) : loopUnavailable ? (
                        <Empty className="border border-dashed py-8">
                            <EmptyHeader>
                                <EmptyTitle>This loop didn’t load</EmptyTitle>
                                <EmptyDescription>Check your connection and try again.</EmptyDescription>
                            </EmptyHeader>
                            <EmptyContent>
                                <Button
                                    variant="outline"
                                    loading={loopLoading}
                                    onClick={() => loadLoop()}
                                    data-attr="today-space-loop-retry"
                                >
                                    Try again
                                </Button>
                            </EmptyContent>
                        </Empty>
                    ) : (
                        <div aria-hidden className="flex flex-col gap-7">
                            <Skeleton className="h-48 w-full" />
                            <Skeleton className="h-24 w-full" />
                        </div>
                    )}
                </div>

                {loop && (
                    <AlertDialog open={deleteOpen} onOpenChange={(open: boolean) => setDeleteOpen(open)}>
                        <AlertDialogContent>
                            <AlertDialogHeader>
                                <AlertDialogTitle>{`Delete ${name}?`}</AlertDialogTitle>
                                <AlertDialogDescription>
                                    This stops every trigger and can’t be undone. Run history stays in the space.
                                </AlertDialogDescription>
                            </AlertDialogHeader>
                            <AlertDialogFooter>
                                <AlertDialogClose render={<Button variant="outline" />}>Cancel</AlertDialogClose>
                                <Button
                                    variant="destructive-outline"
                                    loading={deleting}
                                    onClick={deleteLoop}
                                    data-attr="today-space-loop-delete-confirm"
                                >
                                    Delete
                                </Button>
                            </AlertDialogFooter>
                        </AlertDialogContent>
                    </AlertDialog>
                )}
                <AlertDialog open={!!stopRunTarget} onOpenChange={(open: boolean) => !open && setStopRunTarget(null)}>
                    <AlertDialogContent>
                        <AlertDialogHeader>
                            <AlertDialogTitle>Stop this run?</AlertDialogTitle>
                            <AlertDialogDescription>
                                The agent stops and its sandbox shuts down. The run’s session stays in the space.
                            </AlertDialogDescription>
                        </AlertDialogHeader>
                        <AlertDialogFooter>
                            <AlertDialogClose render={<Button variant="outline" />}>Keep running</AlertDialogClose>
                            <Button
                                variant="destructive-outline"
                                loading={stoppingRun}
                                onClick={stopRun}
                                data-attr="today-space-loop-run-stop-confirm"
                            >
                                Stop run
                            </Button>
                        </AlertDialogFooter>
                    </AlertDialogContent>
                </AlertDialog>
            </SceneContent>
        </TooltipProvider>
    )
}
