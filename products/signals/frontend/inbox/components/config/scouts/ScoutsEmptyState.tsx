import { useActions, useValues } from 'kea'

import { IconCompass } from '@posthog/icons'

import { cn } from 'lib/utils/css-classes'

import { scoutFleetLogic } from '../../../logics/scoutFleetLogic'
import { scoutSuggestionsLogic } from '../../../logics/scoutSuggestionsLogic'
import { ScoutCreateButton } from './ScoutCreateButton'
import { ScoutHelperSkillLinks } from './ScoutHelperSkillLinks'
import { ScoutSuggestButton } from './ScoutSuggestButton'
import { ScoutSuggestionsEmptyStateCards } from './ScoutSuggestionsStrip'

export function ScoutsEmptyState(): JSX.Element {
    const { loadScoutConfigs } = useActions(scoutFleetLogic)
    // A project with picks waiting gets them as the body of the empty state. Without picks the
    // empty state stays exactly as it was.
    const { hasPicks } = useValues(scoutSuggestionsLogic)

    return (
        <div
            className={cn(
                'mx-auto flex flex-col items-center gap-2 py-12 text-center',
                hasPicks ? 'w-full' : 'max-w-md'
            )}
        >
            <div className="mb-1 flex h-12 w-12 items-center justify-center rounded-full bg-fill-primary text-secondary">
                <IconCompass className="text-2xl" />
            </div>
            <h3 className="m-0 text-base font-semibold">No scouts on this project yet</h3>
            <p className="m-0 max-w-md text-sm text-tertiary">
                {hasPicks
                    ? 'Here is what PostHog would watch on this project. Turn one on, or write your own.'
                    : 'Create a scout to investigate a recurring signal or behavior on a schedule.'}
            </p>
            {hasPicks && (
                <div className="mt-3 w-full text-left">
                    <ScoutSuggestionsEmptyStateCards />
                </div>
            )}
            <div className="mt-1 flex flex-wrap items-center justify-center gap-2">
                <ScoutCreateButton onCreated={() => loadScoutConfigs()} />
                <ScoutSuggestButton />
            </div>
            <ScoutHelperSkillLinks />
        </div>
    )
}
