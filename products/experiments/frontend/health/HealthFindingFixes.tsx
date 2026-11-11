import type { ExperimentHealthFindingActionKind } from './experimentHealthFindingEvents'
import { HealthFindingActionButton } from './HealthFindingActionButton'
import { HealthPanelSection } from './HealthPanelSection'

// What each action does and what it changes, so a reader can pick one before clicking.
const FIXES: Record<ExperimentHealthFindingActionKind, { title: string; description: string }> = {
    open_feature_flag: {
        title: 'Open the feature flag',
        description: 'Opens the feature flag in a new tab. A change there applies to every experiment on the flag.',
    },
    open_feature_flag_history: {
        title: "See the flag's history",
        description: 'Opens the changes to the feature flag in a new tab, with the time of each one. Nothing changes.',
    },
    adjust_distribution: {
        title: 'Change the variant split',
        description:
            'An even split keeps the variants the same size, and the rollout then decides how many users enter. A change after launch can move users who were already exposed to another variant.',
    },
    use_first_seen_variant: {
        title: 'Count users in the first variant they saw',
        description:
            'Sets the multiple variant handling to "Use first seen variant", so the results count each of these users in the variant they saw first. Your users see no change.',
    },
    edit_exposure_criteria: {
        title: 'Change the exposure criteria',
        description:
            'The exposure criteria decide which events and users count as exposed. The next calculation of the results uses the new criteria. Your users see no change.',
    },
    edit_release_conditions: {
        title: 'Change the release conditions',
        description:
            'The release conditions decide who gets a variant. A change after launch can let in other users or move users to another variant.',
    },
    add_primary_metric: {
        title: 'Add a primary metric',
        description: 'Adds a metric that the experiment compares the variants on. Your users see no change.',
    },
    add_secondary_metric: {
        title: 'Add a secondary metric',
        description: 'Adds a metric to watch next to the primary metrics. Your users see no change.',
    },
    end_experiment: {
        title: 'End the experiment',
        description:
            "Users and events after the end date don't count in the results. In the next step you choose whether to roll out a variant or leave the feature flag as it is.",
    },
    freeze_exposure: {
        title: 'Freeze exposure',
        description:
            'New users stop entering the experiment. Users already in it keep their variant, and their events keep counting. You can unfreeze it later.',
    },
}

export function HealthFindingFixes({
    actions,
    onActedOn,
}: {
    actions: ExperimentHealthFindingActionKind[]
    onActedOn: (actionKind: ExperimentHealthFindingActionKind) => void
}): JSX.Element {
    return (
        <HealthPanelSection title="Ways to fix">
            <ul className="m-0 flex max-w-xl list-none flex-col divide-y rounded border p-0">
                {actions.map((actionKind) => (
                    <li key={actionKind} className="flex flex-wrap items-start justify-between gap-2 px-3 py-2">
                        <div className="flex min-w-0 flex-1 basis-60 flex-col gap-0.5">
                            <span className="font-semibold">{FIXES[actionKind].title}</span>
                            <span className="text-secondary">{FIXES[actionKind].description}</span>
                        </div>
                        <HealthFindingActionButton actionKind={actionKind} onClick={() => onActedOn(actionKind)} />
                    </li>
                ))}
            </ul>
        </HealthPanelSection>
    )
}
