import type { PatchedFeatureFlagPartialUpdateRequestSchemaApi, RollbackReasonEnumApi } from './generated/api.schemas'

/** What the person chose when a save asked why the edit lowers the flag's exposure. */
export type RollbackReasonAnswer = { reason: RollbackReasonEnumApi; note: string } | 'skipped'

export type RollbackReasonRequestFields = Pick<
    PatchedFeatureFlagPartialUpdateRequestSchemaApi,
    'ask_rollback_reason' | 'rollback_reason' | 'rollback_reason_note'
>

/**
 * The PATCH body fields for an edit. A resend after the question carries the answer, or nothing when the person
 * skipped it, so the server always saves the resend.
 */
export function rollbackReasonRequestFields(
    answer: RollbackReasonAnswer | undefined,
    ask: boolean
): RollbackReasonRequestFields {
    if (answer === 'skipped') {
        return {}
    }
    if (answer) {
        return { rollback_reason: answer.reason, rollback_reason_note: answer.note || null }
    }
    return ask ? { ask_rollback_reason: true } : {}
}
