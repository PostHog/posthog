import { useActions } from 'kea'

import { IconCompass } from '@posthog/icons'

import { scoutFleetLogic } from '../../../logics/scoutFleetLogic'
import { ScoutCreateButton } from './ScoutCreateButton'
import { ScoutHelperSkillLinks } from './ScoutHelperSkillLinks'
import { ScoutSuggestButton } from './ScoutSuggestButton'

export function ScoutsEmptyState(): JSX.Element {
    const { loadScoutConfigs } = useActions(scoutFleetLogic)

    return (
        <div className="mx-auto flex max-w-md flex-col items-center gap-2 py-12 text-center">
            <div className="mb-1 flex h-12 w-12 items-center justify-center rounded-full bg-fill-primary text-secondary">
                <IconCompass className="text-2xl" />
            </div>
            <h3 className="m-0 text-base font-semibold">No scouts on this project yet</h3>
            <p className="m-0 text-sm text-tertiary">
                Create a scout to investigate a recurring signal or behavior on a schedule.
            </p>
            <div className="mt-1 flex flex-wrap items-center justify-center gap-2">
                <ScoutCreateButton onCreated={() => loadScoutConfigs()} />
                <ScoutSuggestButton />
            </div>
            <ScoutHelperSkillLinks />
        </div>
    )
}
