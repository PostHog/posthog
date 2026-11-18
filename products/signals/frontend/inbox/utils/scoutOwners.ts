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

export interface ScoutOwnerOption {
    uuid: string
    name: string
    email: string
    count: number
}

/**
 * Everyone who owns a scout on this fleet, most scouts first. Derived from the roster like the tag
 * options are, so the filter can only offer an owner that some scout actually matches.
 */
export function listScoutOwnerOptions(configs: SignalScoutConfigApi[]): ScoutOwnerOption[] {
    const options = new Map<string, ScoutOwnerOption>()
    for (const config of configs) {
        if (!showsScoutOwnership(config)) {
            continue
        }
        for (const owner of config.owners ?? []) {
            const existing = options.get(owner.uuid)
            if (existing) {
                existing.count += 1
                continue
            }
            options.set(owner.uuid, {
                uuid: owner.uuid,
                name: scoutOwnerName(owner),
                email: owner.email,
                count: 1,
            })
        }
    }
    return [...options.values()].sort(
        (first, second) => second.count - first.count || first.name.localeCompare(second.name)
    )
}

/**
 * Whose scouts to show. Held to the same ownership rule the roster displays, so a scout can never
 * match an owner the row itself doesn't name.
 */
export function configMatchesScoutOwner(config: SignalScoutConfigApi, ownerUuid: string | null): boolean {
    if (!ownerUuid) {
        return true
    }
    if (!showsScoutOwnership(config)) {
        return false
    }
    return (config.owners ?? []).some((owner) => owner.uuid === ownerUuid)
}
