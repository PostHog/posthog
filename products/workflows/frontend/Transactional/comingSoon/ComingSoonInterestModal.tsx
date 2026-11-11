import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal, LemonTextArea } from '@posthog/lemon-ui'

import { ComingSoonInterestLogicProps, comingSoonInterestLogic } from './comingSoonInterestLogic'

const NOTE_MAX_LENGTH = 5000

export interface ComingSoonInterestModalProps {
    survey: ComingSoonInterestLogicProps
    title: string
    /** The survey's open question, word for word, so answers read correctly in the results. */
    question: string
    placeholder: string
    'data-attr': string
}

export function ComingSoonInterestModal({
    survey,
    title,
    question,
    placeholder,
    'data-attr': dataAttr,
}: ComingSoonInterestModalProps): JSX.Element {
    const logic = comingSoonInterestLogic(survey)
    const { noteOpen, note, noteSent } = useValues(logic)
    const { closeNote, setNote, submitNote } = useActions(logic)

    return (
        <LemonModal
            isOpen={noteOpen}
            onClose={closeNote}
            title={title}
            description="Thanks, we counted your interest. A note is optional."
            width={520}
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeNote} data-attr={`${dataAttr}-not-now`}>
                        Not now
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        disabledReason={note.trim() ? undefined : 'Write a note first'}
                        onClick={submitNote}
                        data-attr={`${dataAttr}-send`}
                    >
                        {noteSent ? 'Update note' : 'Send note'}
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-2" data-attr={`${dataAttr}-note`}>
                <div className="font-semibold">{question}</div>
                <LemonTextArea
                    value={note}
                    onChange={setNote}
                    onPressCmdEnter={submitNote}
                    placeholder={placeholder}
                    maxLength={NOTE_MAX_LENGTH}
                    minRows={3}
                    autoFocus
                    data-attr={`${dataAttr}-note-text`}
                />
            </div>
        </LemonModal>
    )
}
