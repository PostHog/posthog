import type { LemonRadioOption } from 'lib/lemon-ui/LemonRadio'

import type { WarehouseSuggestionDismissalReasonEnumApi } from './generated/api.schemas'

type DismissReason = WarehouseSuggestionDismissalReasonEnumApi

export const DEFAULT_DISMISS_REASON: DismissReason = 'not_useful'
export const DISMISS_NOTE_MAX_LENGTH = 1000
export const DISMISS_REASON_LEGEND = 'Why'
export const DISMISS_NOTE_LABEL = 'Anything else? (optional)'
export const DISMISS_NOTE_PLACEHOLDER = 'What would have made this suggestion useful?'

const NOT_NOW: LemonRadioOption<DismissReason> = {
    value: 'not_now',
    label: 'Not now',
    description: 'It can be suggested again if the case for it grows a lot.',
}

const DISMISS_REASONS: LemonRadioOption<DismissReason>[] = [
    { value: 'not_useful', label: 'Not useful', description: "The change wouldn't help." },
    {
        value: 'wrong_estimate',
        label: 'The numbers look wrong',
        description: "The cost or savings don't match what you see.",
    },
    { value: 'already_handled', label: 'Already handled', description: 'You handle this another way.' },
    { value: 'not_owner', label: 'Someone else decides', description: 'This view or table is owned by someone else.' },
    { value: 'other', label: 'Another reason', description: 'Tell us in the note below.' },
]

export function dismissReasonChoices(
    dataAttrPrefix: string,
    { includeNotNow }: { includeNotNow: boolean }
): LemonRadioOption<DismissReason>[] {
    return (includeNotNow ? [NOT_NOW, ...DISMISS_REASONS] : DISMISS_REASONS).map((choice) => ({
        ...choice,
        'data-attr': `${dataAttrPrefix}-${choice.value.replaceAll('_', '-')}`,
    }))
}

export function trimmedNote(note: string): string | undefined {
    return note.trim() || undefined
}
