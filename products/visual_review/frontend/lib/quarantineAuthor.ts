import type { BaselineQuarantineSummaryApi } from '../generated/api.schemas'

type QuarantineAuthorFields = Pick<BaselineQuarantineSummaryApi, 'created_by' | 'source'>

export const QUARANTINED_AUTOMATICALLY = 'Quarantined automatically'

export function automaticQuarantineLabel(
    quarantine: QuarantineAuthorFields,
    label: string = QUARANTINED_AUTOMATICALLY
): string | null {
    if (quarantine.created_by || quarantine.source !== 'auto') {
        return null
    }
    return label
}

/** Who quarantined the snapshot: the user's name through `formatUser`, the automatic label, or null when unknown. */
export function quarantineAuthor(
    quarantine: QuarantineAuthorFields,
    formatUser: (name: string) => string = (name) => name,
    automaticLabel: string = QUARANTINED_AUTOMATICALLY
): string | null {
    if (quarantine.created_by) {
        return formatUser(quarantine.created_by.first_name || quarantine.created_by.email)
    }
    return automaticQuarantineLabel(quarantine, automaticLabel)
}
