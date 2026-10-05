export interface AiDecisionPaletteEntry {
    disabledReason: string | undefined
}

const NOT_APPROVED_REASON =
    "Your organization hasn't approved AI data processing yet. An admin can approve it in Organization settings, under AI service providers."

/** Null when the step palette leaves AI decisions out entirely. */
export function getAiDecisionPaletteEntry({
    flagEnabled,
    dataProcessingAccepted,
}: {
    flagEnabled: boolean
    dataProcessingAccepted: boolean
}): AiDecisionPaletteEntry | null {
    if (!flagEnabled) {
        return null
    }
    return { disabledReason: dataProcessingAccepted ? undefined : NOT_APPROVED_REASON }
}
