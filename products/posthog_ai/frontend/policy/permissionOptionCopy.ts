import type { ApprovalCardOption } from './permissionUtils'

export const FEEDBACK_PLACEHOLDER = 'Tell the agent what to do differently'

/** A decline that relays feedback is answered through its inline textarea, not a plain click. */
export function isFeedbackOption(option: ApprovalCardOption): boolean {
    return option.requiresFeedback || option.supportsFeedback
}

export function optionRowLabel(option: ApprovalCardOption): string {
    // The wire's feedback option describes the interaction ("Type here to tell the agent…") instead of
    // naming the choice; the textarea placeholder carries that instruction, the row just needs a name.
    if (isFeedbackOption(option) && /^type here\b/i.test(option.label)) {
        return 'Do it differently…'
    }
    return option.label
}

export function optionSublabel(option: ApprovalCardOption): string | null {
    if (option.hint) {
        return option.hint
    }
    if (option.requiresFeedback) {
        return 'The agent adjusts and continues instead of stopping this turn.'
    }
    if (option.supportsFeedback) {
        return 'With a note the agent adjusts and continues. Without one, declining stops this turn.'
    }
    if (option.decision === 'declined') {
        return 'Stops this turn. Send a follow-up to redirect the agent.'
    }
    return null
}
