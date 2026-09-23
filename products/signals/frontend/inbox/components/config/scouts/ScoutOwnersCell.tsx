import { ProfileBubbles } from 'lib/lemon-ui/ProfilePicture/ProfileBubbles'

import type { SignalScoutConfigApi as SignalScoutConfig } from 'products/signals/frontend/generated/api.schemas'

import { scoutOwnerBubbles, showsScoutOwnership } from '../../../utils/scoutOwners'

/**
 * The roster's owner column: faces only, so a whole fleet can be scanned for unowned scouts in one
 * pass. Names are on hover, and the scout page spells the ownership rule out in full.
 */
export function ScoutOwnersCell({ config }: { config: SignalScoutConfig }): JSX.Element | null {
    if (!showsScoutOwnership(config)) {
        return null
    }

    // Empty rather than undefined while an older API pod, mid-rollout, still omits the field.
    const owners = config.owners ?? []
    if (owners.length === 0) {
        return <span className="text-xs text-muted">No owner</span>
    }

    const people = scoutOwnerBubbles(owners)
    return <ProfileBubbles limit={3} people={people} tooltip={people.map((person) => person.title).join(', ')} />
}
