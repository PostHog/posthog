import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal, LemonTextArea } from '@posthog/lemon-ui'

import { LemonRadio } from 'lib/lemon-ui/LemonRadio'

import {
    DISMISS_NOTE_LABEL,
    DISMISS_NOTE_MAX_LENGTH,
    DISMISS_NOTE_PLACEHOLDER,
    DISMISS_REASON_LEGEND,
    dismissReasonChoices,
} from '../dismissReasons'
import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'

const REASON_CHOICES = dismissReasonChoices('warehouse-suggestions-dismiss-reason', { includeNotNow: false })

export function DismissSuggestionModal(): JSX.Element | null {
    const { dismissDialogSuggestion, dismissReason, dismissNote } = useValues(warehouseSuggestionsLogic)
    const { closeDismissDialog, setDismissReason, setDismissNote, confirmDismiss } =
        useActions(warehouseSuggestionsLogic)

    if (!dismissDialogSuggestion) {
        return null
    }

    return (
        <LemonModal
            isOpen
            onClose={closeDismissDialog}
            title={`Dismiss the suggestion for ${dismissDialogSuggestion.payload.subject_name}?`}
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeDismissDialog}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={() => confirmDismiss()}
                        data-attr="warehouse-suggestions-dismiss-confirm"
                    >
                        Dismiss
                    </LemonButton>
                </>
            }
        >
            <div className="flex max-w-xl flex-col gap-4">
                <p className="m-0 text-sm text-secondary">It won't be suggested again.</p>
                <fieldset className="flex flex-col gap-2">
                    <h4 className="m-0 text-sm font-semibold">{DISMISS_REASON_LEGEND}</h4>
                    <LemonRadio
                        aria-label={DISMISS_REASON_LEGEND}
                        value={dismissReason}
                        onChange={setDismissReason}
                        options={REASON_CHOICES}
                        radioPosition="top"
                    />
                </fieldset>
                <div className="flex flex-col gap-2">
                    <h4 className="m-0 text-sm font-semibold">{DISMISS_NOTE_LABEL}</h4>
                    <LemonTextArea
                        aria-label={DISMISS_NOTE_LABEL}
                        value={dismissNote}
                        onChange={setDismissNote}
                        maxLength={DISMISS_NOTE_MAX_LENGTH}
                        placeholder={DISMISS_NOTE_PLACEHOLDER}
                        minRows={3}
                        data-attr="warehouse-suggestions-dismiss-note"
                    />
                </div>
            </div>
        </LemonModal>
    )
}
