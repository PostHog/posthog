import { useActions } from 'kea'

import { IconCompass } from '@posthog/icons'

import { scoutFleetLogic } from '../../../logics/scoutFleetLogic'
import { ScoutCreateButton } from './ScoutCreateButton'
import { ScoutHelperSkillLinks } from './ScoutHelperSkillLinks'
import { ScoutSuggestButton } from './ScoutSuggestButton'

export function ScoutsEmptyState(): JSX.Element {
    const { loadScoutConfigs } = useActions(scoutFleetLogic)

    return (
        <div className="m-6 flex flex-col items-start gap-2 rounded border border-primary bg-surface-primary px-5 py-5">
            <div className="flex items-center gap-2">
                <IconCompass className="size-[18px] text-accent" />
                <span className="text-sm font-medium text-default">No scouts on this project yet</span>
            </div>
            <p className="mb-0 max-w-2xl text-xs leading-snug text-secondary">
                Create a scout to investigate a recurring signal or behavior on a schedule.
            </p>
            <div className="flex flex-wrap items-center gap-2">
                <ScoutCreateButton onCreated={() => loadScoutConfigs()} />
                <ScoutSuggestButton />
            </div>
            <ScoutHelperSkillLinks />
        </div>
    )
}
