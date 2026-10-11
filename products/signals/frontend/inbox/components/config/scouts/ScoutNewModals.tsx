import { useActions, useValues } from 'kea'

import type { SignalScoutCreateResponseApi } from 'products/signals/frontend/generated/api.schemas'

import { captureScoutCreatePathSwitched, type ScoutSurface } from '../../../inboxAnalytics'
import { type ScoutNewModal, scoutNewModalLogic } from '../../../logics/scoutNewModalLogic'
import { SCOUT_CHAT_PROMPT_MAX_LENGTH, ScoutChatModal } from './ScoutChatModal'
import { ScoutCreateModalHost } from './ScoutCreateModalHost'

export interface ScoutNewModalsProps {
    /** Only render a modal that this surface's button opened. Omit to render the modal for any surface. */
    surface?: ScoutSurface
    onCreated?: (scout: SignalScoutCreateResponseApi) => void
}

/** The chat and form modals that "New scout" opens. Each modal links to the other and carries the typed text across. */
export function ScoutNewModals({ surface: hostSurface, onCreated }: ScoutNewModalsProps): JSX.Element | null {
    const { openModal } = useValues(scoutNewModalLogic)
    const { setOpenModal, closeModal } = useActions(scoutNewModalLogic)
    if (!openModal || (hostSurface && openModal.surface !== hostSurface)) {
        return null
    }
    const { surface, modal } = openModal
    const setModal = (next: ScoutNewModal): void => setOpenModal({ surface, modal: next })

    return (
        <>
            {modal.kind === 'chat' ? (
                <ScoutChatModal
                    initialPrompt={modal.prompt}
                    onClose={closeModal}
                    onSwitchToForm={(prompt) => {
                        captureScoutCreatePathSwitched({ direction: 'chat_to_form', surface })
                        // The chat allows a longer request than the form's description. Carry all of it, so the
                        // form marks the description as too long and the person decides what to cut.
                        setModal(
                            modal.formInitialValues
                                ? {
                                      kind: 'form',
                                      initialValues: modal.formInitialValues,
                                      descriptionOverride: prompt,
                                  }
                                : { kind: 'form', initialValues: prompt ? { description: prompt } : {} }
                        )
                    }}
                />
            ) : null}
            <ScoutCreateModalHost
                initialValues={modal.kind === 'form' ? modal.initialValues : null}
                descriptionOverride={modal.kind === 'form' ? modal.descriptionOverride : undefined}
                onClose={closeModal}
                onCreated={onCreated}
                onSwitchToChat={(description) => {
                    captureScoutCreatePathSwitched({ direction: 'form_to_chat', surface })
                    setModal({
                        kind: 'chat',
                        prompt: description.slice(0, SCOUT_CHAT_PROMPT_MAX_LENGTH),
                        formInitialValues: modal.kind === 'form' ? modal.initialValues : undefined,
                    })
                }}
            />
        </>
    )
}
