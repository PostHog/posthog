import { Tooltip } from '@posthog/lemon-ui'

import { ProfileBubbles } from 'lib/lemon-ui/ProfilePicture/ProfileBubbles'

import type { SignalScoutConfigApi as SignalScoutConfig } from 'products/signals/frontend/generated/api.schemas'

import { scoutOwnerBubbles, scoutOwnersLabel, showsScoutOwnership } from '../../../utils/scoutOwners'

const OWNERSHIP_EXPLAINER =
    "Owners are set on the scout's skill, so editing or pausing the scout does not change them. Reports this scout files suggest them as reviewers."

/**
 * Who to talk to when a custom scout turns noisy or wrong, on its page. A canonical scout is
 * PostHog's to maintain, so it says nothing.
 */
export function ScoutOwners({ config }: { config: SignalScoutConfig }): JSX.Element | null {
    if (!showsScoutOwnership(config)) {
        return null
    }

    // Empty rather than undefined while an older API pod, mid-rollout, still omits the field.
    const owners = config.owners ?? []
    if (owners.length === 0) {
        // Named rather than left blank: an unowned scout still files into a shared inbox, and the
        // gap is the thing a reader needs to see.
        return (
            <Tooltip title={`Nobody owns this scout. ${OWNERSHIP_EXPLAINER}`}>
                <span className="text-xs text-muted">No owner</span>
            </Tooltip>
        )
    }

    const people = scoutOwnerBubbles(owners)
    return (
        <Tooltip title={`${people.map((person) => person.title).join(', ')}. ${OWNERSHIP_EXPLAINER}`}>
            <span className="flex items-center gap-1.5">
                <ProfileBubbles limit={4} people={people} />
                <span className="text-xs text-secondary">{scoutOwnersLabel(owners)}</span>
            </span>
        </Tooltip>
    )
}
