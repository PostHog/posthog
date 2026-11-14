import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconFlag } from '@posthog/icons'
import {
    Button,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyMedia,
    EmptyTitle,
    Skeleton,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { ReleaseDetailsCard } from './ReleaseDetailsCard'
import { ReleaseHistory } from './ReleaseHistory'
import { ReleaseLinkedCard } from './ReleaseLinkedCard'
import { ReleaseLoadError } from './ReleaseLoadError'
import { releaseLogic } from './releaseLogic'
import { ReleasePartialLoadWarning } from './ReleasePartialLoadWarning'
import { ReleaseScheduleButton } from './ReleaseScheduleButton'
import { ReleaseScheduleDialog } from './ReleaseScheduleDialog'
import { ReleasesGate } from './ReleasesGate'
import { ReleaseStatusCard } from './ReleaseStatusCard'
import { ReleaseSuggestedCard } from './ReleaseSuggestedCard'
import { ReleaseTrackCard } from './ReleaseTrackCard'
import { STAGE_COLOR_VARS } from './releaseUtils'

interface ReleaseSceneProps {
    id?: string
}

export const scene: SceneExport<ReleaseSceneProps> = {
    component: Release,
    logic: releaseLogic,
    paramsToProps: ({ params: { id } }) => ({ id }),
}

function ReleaseSkeleton({ suggestions }: { suggestions: boolean }): JSX.Element {
    return (
        <div data-quill className="@container flex flex-col gap-4" data-attr="release-skeleton">
            <div className="flex flex-col gap-5 pt-1">
                <Skeleton className="h-6 w-48" />
                <Skeleton className="h-5 w-72" />
            </div>
            <div className="grid items-start gap-4 @3xl:grid-cols-3">
                <div className="flex flex-col gap-4 @3xl:col-span-2">
                    <Skeleton className="h-76 w-full" />
                    <Skeleton className="h-52 w-full" />
                    <Skeleton className="h-60 w-full" />
                </div>
                <div className="flex flex-col gap-4">
                    <Skeleton className="h-20 w-full" />
                    <Skeleton className="h-44 w-full" />
                    {suggestions && <Skeleton className="h-40 w-full" />}
                </div>
            </div>
        </div>
    )
}

function ReleaseContent({ id }: ReleaseSceneProps): JSX.Element {
    const { rows, dataLoading, loadFailed, canEditReleases } = useValues(releaseLogic)
    const { updateRelease, autoLinkBroadcasts } = useActions(releaseLogic)
    const row = rows.find((item) => item.id === id)
    const loaded = !!row

    useEffect(() => {
        if (loaded && canEditReleases && id) {
            autoLinkBroadcasts(id)
        }
    }, [id, loaded, canEditReleases, autoLinkBroadcasts])

    if (!row) {
        return (
            <SceneContent>
                {loadFailed ? (
                    <ReleaseLoadError title="This release could not load" />
                ) : dataLoading ? (
                    <ReleaseSkeleton suggestions={canEditReleases} />
                ) : (
                    <div data-quill>
                        <Empty>
                            <EmptyHeader>
                                <EmptyMedia variant="icon">
                                    <IconFlag />
                                </EmptyMedia>
                                <EmptyTitle>This release does not exist</EmptyTitle>
                                <EmptyDescription>It may have been deleted, or the link is wrong.</EmptyDescription>
                            </EmptyHeader>
                            <EmptyContent>
                                <Button
                                    variant="outline"
                                    nativeButton={false}
                                    render={<LinkPrimitive to={urls.releaseList()} />}
                                >
                                    See all releases
                                </Button>
                            </EmptyContent>
                        </Empty>
                    </div>
                )}
            </SceneContent>
        )
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name={row.name}
                description={row.description}
                resourceType={{ type: 'release', forceIcon: <IconFlag /> }}
                canEdit={canEditReleases}
                renameDebounceMs={800}
                onNameChange={(name) => updateRelease(row.id, { name })}
                onDescriptionChange={(description) => updateRelease(row.id, { description })}
                actions={
                    <div data-quill>
                        <ReleaseScheduleButton row={row} />
                    </div>
                }
            />
            <div data-quill className={`@container flex flex-col gap-4 pb-8 ${STAGE_COLOR_VARS}`}>
                <ReleasePartialLoadWarning />
                <div className="grid items-start gap-4 @3xl:grid-cols-3">
                    <div className="flex min-w-0 flex-col gap-4 @3xl:col-span-2">
                        <ReleaseStatusCard row={row} />
                        <ReleaseTrackCard row={row} />
                        <ReleaseHistory row={row} />
                    </div>
                    <div className="flex min-w-0 flex-col gap-4">
                        <ReleaseDetailsCard row={row} />
                        <ReleaseLinkedCard row={row} />
                        <ReleaseSuggestedCard row={row} />
                    </div>
                </div>
                <ReleaseScheduleDialog />
            </div>
        </SceneContent>
    )
}

export function Release({ id }: ReleaseSceneProps): JSX.Element {
    return (
        <ReleasesGate>
            <ReleaseContent id={id} />
        </ReleasesGate>
    )
}
