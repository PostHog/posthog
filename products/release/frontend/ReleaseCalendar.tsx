import { useValues } from 'kea'

import { IconFlag } from '@posthog/icons'

import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { NewReleaseButton, NewReleaseDialog, ReleaseFilters } from './ReleaseFilters'
import { ReleaseLoadError } from './ReleaseLoadError'
import { releaseLogic } from './releaseLogic'
import { ReleasePartialLoadWarning } from './ReleasePartialLoadWarning'
import { ReleasesGate } from './ReleasesGate'
import { ReleaseTimeline } from './ReleaseTimeline'

export const scene: SceneExport = {
    component: ReleaseCalendar,
    logic: releaseLogic,
}

function ReleaseCalendarContent(): JSX.Element {
    const { loadFailed } = useValues(releaseLogic)
    return (
        <SceneContent>
            <SceneTitleSection
                name="Release calendar"
                description="One row for each release, with its flags, experiments, early access and scheduled changes."
                resourceType={{ type: 'release', forceIcon: <IconFlag /> }}
                actions={
                    <div data-quill>
                        <NewReleaseButton />
                    </div>
                }
            />
            <div data-quill className="flex flex-col gap-3">
                <ReleaseFilters />
                <ReleasePartialLoadWarning />
                {loadFailed ? <ReleaseLoadError title="Releases could not load" /> : <ReleaseTimeline />}
                <NewReleaseDialog />
            </div>
        </SceneContent>
    )
}

export function ReleaseCalendar(): JSX.Element {
    return (
        <ReleasesGate>
            <ReleaseCalendarContent />
        </ReleasesGate>
    )
}
