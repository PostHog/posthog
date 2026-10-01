import { useActions, useValues } from 'kea'

import { IconCopy, IconExternal, IconPause, IconPlay, IconTrash } from '@posthog/icons'
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
    TooltipProvider,
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
    } = useValues(logic)
    const { loadLoop, setEnabled, runNow, copyLink, deleteLoop, setDeleteOpen } = useActions(logic)

    if (!railNavEnabled || !loopsEnabled || loopMissing) {
        return <NotFound object="loop" />
    }

    const name = loop ? loop.name || 'Untitled loop' : null
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
                            <Badge variant={loop.status.variant} className="shrink-0">
                                {loop.status.label}
                            </Badge>
                        ) : null
                    }
                    actions={
                        loop ? (
                            <div className="flex flex-wrap items-center gap-1">
                                <Button
                                    size="sm"
                                    variant="outline"
                                    loading={savingEnabled}
                                    onClick={() => setEnabled(!loop.enabled)}
                                    data-attr="today-space-loop-toggle"
                                >
                                    {loop.enabled ? <IconPause /> : <IconPlay />}
                                    {loop.enabled ? 'Pause' : 'Resume'}
                                </Button>
                                {loop.canRunNow && (
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
                                {/* Web has no loop form yet, so editing opens the loop in PostHog Desktop. */}
                                <Button
                                    size="sm"
                                    variant="outline"
                                    render={<LinkPrimitive to={urls.codeLoopLink(loop.id)} target="_blank" />}
                                    data-attr="today-space-loop-edit"
                                >
                                    <IconExternal />
                                    Edit in Desktop
                                </Button>
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
                    {!loop ? (
                        loopUnavailable ? (
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
                        )
                    ) : (
                        <>
                            <SpaceLoopConfiguration loop={loop} />
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
                            >
                                {runsLoading && !runs ? (
                                    <Skeleton className="h-16 w-full" />
                                ) : !runs?.length ? (
                                    <Empty className="border border-dashed py-8">
                                        <EmptyHeader>
                                            <EmptyTitle>No runs yet</EmptyTitle>
                                            <EmptyDescription>
                                                {loop.canRunNow
                                                    ? 'Runs show here once this loop fires. Start one with Run now, or wait for its next trigger.'
                                                    : 'Runs show here once this loop fires.'}
                                            </EmptyDescription>
                                        </EmptyHeader>
                                    </Empty>
                                ) : (
                                    <ItemGroup combined>
                                        {runs.map((run) => (
                                            <SpaceLoopRunRow key={run.id} run={run} />
                                        ))}
                                    </ItemGroup>
                                )}
                            </SpaceSettingsSection>
                        </>
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
            </SceneContent>
        </TooltipProvider>
    )
}
