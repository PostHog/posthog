import { HogFlowActionValidationResult } from '../types'

// The reasons a step is invalid, or an empty list when there's nothing to show yet. An email step
// is invalid the moment it's added (a template ships no sender), but its field messages are held
// back until a save attempt - so with no reason, stay quiet instead of flagging a step the user
// can't act on.
export function validationBadgeReasons(result: HogFlowActionValidationResult | null | undefined): string[] {
    if (!result || result.valid !== false) {
        return []
    }
    return [
        ...Object.values(result.emailErrors ?? {}),
        ...Object.values(result.errors ?? {}),
        ...(result.schema?.issues.map((issue) => issue.message) ?? []),
    ].filter((message): message is string => !!message)
}
