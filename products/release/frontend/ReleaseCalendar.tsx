import { IconFlag } from '@posthog/icons'

import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { NewReleaseButton, NewReleaseDialog, ReleaseFilters } from './ReleaseFilters'
import { releaseLogic } from './releaseLogic'
import { ReleaseTimeline } from './ReleaseTimeline'

export const scene: SceneExport = {
    component: ReleaseCalendar,
    logic: releaseLogic,
}

export function ReleaseCalendar(): JSX.Element {
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
                <ReleaseTimeline />
                <NewReleaseDialog />
            </div>
        </SceneContent>
    )
}
