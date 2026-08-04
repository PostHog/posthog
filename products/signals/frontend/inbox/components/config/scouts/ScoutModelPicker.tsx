import { useActions, useValues } from 'kea'

import { LemonSegmentedButton, LemonSkeleton } from '@posthog/lemon-ui'

import type { LemonSegmentedButtonOption } from 'lib/lemon-ui/LemonSegmentedButton'

import { signalTeamConfigLogic } from '../../../logics/signalTeamConfigLogic'
import { ScoutModel } from '../../../types'

/** Letting PostHog pick is a real choice, so it needs a value the segmented control can hold. */
const AUTO = 'auto'

// Product names rather than raw model ids: the id is an implementation detail, and the choice is
// between three vendors' flagships, not between version strings.
const SEGMENTS: LemonSegmentedButtonOption<ScoutModel | typeof AUTO>[] = [
    {
        value: AUTO,
        label: 'Auto',
        tooltip: 'PostHog picks, and keeps up as models change. Recommended unless you have a reason not to.',
    },
    { value: 'claude-opus-5', label: 'Opus', tooltip: 'Deepest reasoning. Slower and the most expensive to run.' },
    { value: 'claude-fable-5', label: 'Fable', tooltip: 'Fast, and strong at reading unfamiliar code.' },
    { value: 'gpt-5.6-sol', label: 'Sol', tooltip: 'Thorough on long investigations.' },
]

/**
 * Which model this team's scouts run on. Team-wide rather than per-scout: the fleet is meant to be
 * set up once, and a per-scout matrix would be a lot of decisions for a choice most teams make zero
 * times.
 *
 * Only affects scouts. Report research and PR generation are separate steps with their own runtimes.
 */
export function ScoutModelPicker(): JSX.Element {
    const { teamConfig, teamConfigLoading, teamConfigUpdating, scoutModel } = useValues(signalTeamConfigLogic)
    const { patchTeamConfig } = useActions(signalTeamConfigLogic)

    if (teamConfigLoading && teamConfig === null) {
        return <LemonSkeleton className="h-9 w-full rounded" />
    }

    return (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded border border-primary bg-surface-primary px-3 py-2">
            <div className="flex flex-col gap-0.5 min-w-0">
                <span className="text-[13px] font-semibold text-default">Model</span>
                <p className="text-xs text-tertiary leading-snug mb-0">
                    What your scouts think with. Applies to every scout in the fleet.
                </p>
            </div>
            <LemonSegmentedButton
                size="small"
                value={scoutModel ?? AUTO}
                options={SEGMENTS}
                disabledReason={teamConfigUpdating ? 'Saving changes' : undefined}
                onChange={(next) => patchTeamConfig({ scout_model: next === AUTO ? null : next })}
            />
        </div>
    )
}
