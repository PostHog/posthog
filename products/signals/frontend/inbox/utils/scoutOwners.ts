import { fullName } from 'lib/utils/strings'

import type { SignalScoutConfigApi, UserBasicApi } from 'products/signals/frontend/generated/api.schemas'

/**
 * Who answers for a scout, and where saying so is useful.
 *
 * Ownership is recorded on the scout's skill rather than its config, so editing or pausing the
 * scout leaves it unchanged. Canonical scouts are PostHog's to maintain, so an owner is only worth
 * showing (or missing) on a scout a team wrote itself.
 */
export function showsScoutOwnership(config: Pick<SignalScoutConfigApi, 'scout_origin'>): boolean {
    return config.scout_origin === 'custom'
}

export function scoutOwnerName(owner: UserBasicApi): string {
    return fullName(owner) || owner.email
}

/** `ProfileBubbles` people. The email rides in the per-avatar title so a hover names the person. */
export function scoutOwnerBubbles(owners: readonly UserBasicApi[]): { email: string; name: string; title: string }[] {
    return owners.map((owner) => {
        const name = scoutOwnerName(owner)
        return { email: owner.email, name, title: name === owner.email ? name : `${name} (${owner.email})` }
    })
}

export function scoutOwnersLabel(owners: readonly UserBasicApi[]): string {
    return owners.length === 1 ? scoutOwnerName(owners[0]) : `${owners.length} owners`
}
