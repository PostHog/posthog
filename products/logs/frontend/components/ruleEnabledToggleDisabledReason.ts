export function ruleEnabledToggleDisabledReason(
    ruleId: string,
    ruleEnabledTogglePendingId: string | null,
    saveRulesOrderPending: boolean
): string | undefined {
    return ruleEnabledTogglePendingId === ruleId ? 'Saving…' : saveRulesOrderPending ? 'Updating order…' : undefined
}
