import { useActions, useValues } from 'kea'

import { IconArrowLeft, IconCopy, IconExternal, IconPause, IconPlay, IconTrash } from '@posthog/icons'
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
    Card,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    Heading,
    Skeleton,
    Text,
    TooltipProvider,
} from '@posthog/quill'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

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

    const backLink = (
        <LinkPrimitive
            to={urls.taskSpaceLoops(id)}
            className="flex w-fit items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
            data-attr="today-space-loop-back"
        >
            <IconArrowLeft />
            {`Loops in ${spaceName}`}
        </LinkPrimitive>
    )

    if (!loop) {
        return (
            <SceneContent>
                <div className="mx-auto flex w-full max-w-5xl flex-col gap-4" data-quill>
                    {backLink}
                    {loopUnavailable ? (
                        <Empty className="py-12">
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
                        <div aria-hidden className="flex flex-col gap-4">
                            <Skeleton className="h-8 w-2/5" />
                            <Skeleton className="h-4 w-3/5" />
                            <Skeleton className="h-48 w-full" />
                            <Skeleton className="h-32 w-full" />
                        </div>
                    )}
                </div>
            </SceneContent>
        )
    }

    const name = loop.name || 'Untitled loop'
    return (
        <TooltipProvider>
            <SceneContent>
                <div className="mx-auto flex w-full max-w-5xl flex-col gap-6" data-quill>
                    <div className="flex flex-col gap-2">
                        {backLink}
                        <div className="flex flex-wrap items-center justify-between gap-3">
                            <div className="flex min-w-0 items-center gap-2">
                                <Heading size="xl" render={<h1 />} className="truncate">
                                    {name}
                                </Heading>
                                <Badge variant={loop.status.variant} className="shrink-0">
                                    {loop.status.label}
                                </Badge>
                            </div>
                            <div className="flex flex-wrap items-center gap-2">
                                <Button
                                    variant="outline"
                                    loading={savingEnabled}
                                    onClick={() => setEnabled(!loop.enabled)}
                                    data-attr="today-space-loop-toggle"
                                >
                                    {loop.enabled ? <IconPause /> : <IconPlay />}
                                    {loop.enabled ? 'Pause' : 'Resume'}
                                </Button>
                                <Button variant="outline" onClick={copyLink} data-attr="today-space-loop-copy-link">
                                    <IconCopy />
                                    Copy link
                                </Button>
                                {loop.canRunNow && (
                                    <Button
                                        variant="outline"
                                        loading={runningNow}
                                        onClick={runNow}
                                        data-attr="today-space-loop-run-now"
                                    >
                                        <IconPlay />
                                        Run now
                                    </Button>
                                )}
                                {/* Web has no loop form yet, so editing opens the loop in PostHog Desktop. */}
                                <Button
                                    variant="outline"
                                    render={<LinkPrimitive to={urls.codeLoopLink(loop.id)} target="_blank" />}
                                    data-attr="today-space-loop-edit"
                                >
                                    <IconExternal />
                                    Edit in Desktop
                                </Button>
                                <Button
                                    variant="destructive-outline"
                                    onClick={() => setDeleteOpen(true)}
                                    data-attr="today-space-loop-delete"
                                >
                                    <IconTrash />
                                    Delete
                                </Button>
                            </div>
                        </div>
                        {loop.description && (
                            <Text size="sm" variant="muted" className="max-w-3xl">
                                {loop.description}
                            </Text>
                        )}
                    </div>

                    <SpaceLoopConfiguration loop={loop} />

                    <section className="flex flex-col gap-3">
                        <Heading size="sm" render={<h2 />}>
                            Instructions
                        </Heading>
                        <Card className="max-h-96 overflow-y-auto p-4">
                            <Text size="sm" className="whitespace-pre-wrap">
                                {loop.instructions || 'No instructions'}
                            </Text>
                        </Card>
                    </section>

                    <section className="flex flex-col gap-3">
                        <div className="flex items-baseline gap-2">
                            <Heading size="sm" render={<h2 />}>
                                Run history
                            </Heading>
                            <Text render={<span />} size="xs" variant="muted">
                                {`${SPACE_LOOP_RUNS_LIMIT} most recent`}
                            </Text>
                        </div>
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
                            <div className="flex flex-col gap-2">
                                {runs.map((run) => (
                                    <SpaceLoopRunRow key={run.id} run={run} />
                                ))}
                            </div>
                        )}
                    </section>
                </div>

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
            </SceneContent>
        </TooltipProvider>
    )
}
