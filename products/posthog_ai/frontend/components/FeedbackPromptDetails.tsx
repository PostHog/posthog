import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState, memo } from 'react'

import { IconDocument } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal, lemonToast } from '@posthog/lemon-ui'

import { SupportForm } from 'lib/components/Support/SupportForm'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { userLogic } from 'scenes/userLogic'

import { FeedbackPromptLogicProps, feedbackPromptLogic } from '../logics/feedbackPromptLogic'
import { runStreamLogic } from '../logics/runStreamLogic'
import { MessageTemplate } from '../messages/MessageTemplate'
import { FeedbackSessionKind, appendTicketMetadata } from '../utils/ticketMetadata'

/**
 * The detailed form shown after a "Bad" rating on the periodic prompt: free-text feedback, or escalation
 * to a support ticket through the in-app support form.
 */
export const FeedbackPromptDetails = memo(function FeedbackPromptDetails({
    sessionId,
    sessionKind,
    streamKey,
}: FeedbackPromptLogicProps & { sessionKind: FeedbackSessionKind }): JSX.Element {
    const logicProps = { sessionId, streamKey }
    const { submitDetailedFeedback, completeDetailedFeedback } = useActions(feedbackPromptLogic(logicProps))
    const { traceId } = useValues(runStreamLogic)
    const [feedbackText, setFeedbackText] = useState('')
    const [status, setStatus] = useState<'feedback' | 'ticket_preview' | 'done'>('feedback')
    const [hasSubmittedTicket, setHasSubmittedTicket] = useState(false)
    const [isSupportModalOpen, setIsSupportModalOpen] = useState(false)
    const submitInFlightRef = useRef(false)

    const { sendSupportRequest, lastSubmittedTicketId } = useValues(supportLogic)
    const { resetSendSupportRequest } = useActions(supportLogic)
    const { user } = useValues(userLogic)

    const [pendingTicketSubmission, setPendingTicketSubmission] = useState(false)
    const [ticketIdBeforeSubmission, setTicketIdBeforeSubmission] = useState<string | null>(null)
    const [ticketMessageText, setTicketMessageText] = useState<string>('')

    useEffect(() => {
        // The ticket id only exists once the send resolves; a new id means the submit succeeded.
        if (pendingTicketSubmission && lastSubmittedTicketId && lastSubmittedTicketId !== ticketIdBeforeSubmission) {
            submitDetailedFeedback(ticketMessageText || undefined)
            submitInFlightRef.current = false
            setHasSubmittedTicket(true)
            setIsSupportModalOpen(false)
            setPendingTicketSubmission(false)
            completeDetailedFeedback()
        }
    }, [
        lastSubmittedTicketId,
        pendingTicketSubmission,
        ticketIdBeforeSubmission,
        submitDetailedFeedback,
        completeDetailedFeedback,
        ticketMessageText,
    ])

    function submitFeedback(): void {
        submitDetailedFeedback(feedbackText)
        setStatus('done')
        setTimeout(completeDetailedFeedback, 2000)
    }

    function showTicketPreviewOrOpenModal(): void {
        if (feedbackText.trim().length > 0) {
            setStatus('ticket_preview')
        } else {
            openSupportModalWithPrefill()
        }
    }

    function openSupportModalWithPrefill(): void {
        if (hasSubmittedTicket) {
            return
        }
        resetSendSupportRequest({
            name: '',
            email: '',
            kind: 'feedback',
            message: feedbackText,
            ai_conversation_id: sessionId,
            ai_trace_id: traceId,
            ai_feedback_rating: 'bad',
        })
        setIsSupportModalOpen(true)
    }

    async function handleSupportFormSubmit(): Promise<void> {
        if (submitInFlightRef.current || hasSubmittedTicket) {
            return
        }
        const finalMessage = appendTicketMetadata(sendSupportRequest.message, { sessionId, sessionKind, traceId })
        if (!finalMessage) {
            lemonToast.error('Please add a description before creating a ticket.')
            return
        }

        submitInFlightRef.current = true
        setTicketMessageText(sendSupportRequest.message)
        setTicketIdBeforeSubmission(supportLogic.values.lastSubmittedTicketId)
        setPendingTicketSubmission(true)
        try {
            await supportLogic.asyncActions.submitSupportTicket({
                ...sendSupportRequest,
                name: user?.first_name ?? sendSupportRequest.name ?? 'name not set',
                email: user?.email ?? sendSupportRequest.email ?? '',
                message: finalMessage,
            })
        } catch {
            // Failure is detected below via the unchanged ticket id
        }
        // Success closes the modal via the effect above. An unchanged id means the submit failed: clear
        // the pending state so the modal doesn't hang (the error toast already showed, the text stays).
        if (supportLogic.values.lastSubmittedTicketId === ticketIdBeforeSubmission) {
            submitInFlightRef.current = false
            setPendingTicketSubmission(false)
        }
    }

    function handleSupportModalCancel(): void {
        // The in-flight request cannot be aborted; closing now would allow a duplicate ticket.
        if (submitInFlightRef.current) {
            return
        }
        setIsSupportModalOpen(false)
        setPendingTicketSubmission(false)
    }

    const supportModal = (
        <LemonModal
            isOpen={isSupportModalOpen}
            onClose={handleSupportModalCancel}
            title="Give feedback"
            footer={
                <div className="flex items-center gap-2">
                    <LemonButton
                        type="secondary"
                        onClick={handleSupportModalCancel}
                        disabledReason={pendingTicketSubmission ? 'Submitting your ticket…' : undefined}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        data-attr="submit"
                        onClick={() => void handleSupportFormSubmit()}
                        loading={pendingTicketSubmission}
                        disabledReason={hasSubmittedTicket ? 'Ticket already created' : undefined}
                    >
                        Submit
                    </LemonButton>
                </div>
            }
        >
            <SupportForm />
        </LemonModal>
    )

    if (status === 'done') {
        return (
            <MessageTemplate type="ai">
                <p className="m-0 text-sm text-secondary">Thanks for making PostHog AI better!</p>
            </MessageTemplate>
        )
    }

    if (status === 'feedback') {
        return (
            <>
                <MessageTemplate type="ai">
                    <div className="flex flex-col gap-2">
                        <p className="m-0 font-medium">What could we improve?</p>
                        <LemonInput
                            placeholder="Help us improve PostHog AI..."
                            value={feedbackText}
                            onChange={setFeedbackText}
                            onPressEnter={submitFeedback}
                            fullWidth
                            autoFocus
                        />
                        <div className="flex gap-2">
                            <LemonButton type="primary" size="small" onClick={submitFeedback}>
                                Submit
                            </LemonButton>
                            <LemonButton
                                type="secondary"
                                size="small"
                                onClick={showTicketPreviewOrOpenModal}
                                disabledReason={hasSubmittedTicket ? 'Ticket already created' : undefined}
                            >
                                Open support ticket
                            </LemonButton>
                        </div>
                    </div>
                </MessageTemplate>
                {supportModal}
            </>
        )
    }

    return (
        <>
            <MessageTemplate type="ai">
                <div className="flex flex-col gap-3">
                    <div className="flex items-center gap-2">
                        <IconDocument className="text-secondary" />
                        <span className="font-medium">Support ticket ready for review</span>
                    </div>
                    <p className="m-0 text-sm text-secondary">
                        Here's a draft of your support ticket. Please review and submit it to get help from PostHog
                        support.
                    </p>
                    <div className="bg-bg-light border rounded p-3">
                        <div className="text-xs font-medium text-secondary uppercase mb-1">Ticket description</div>
                        <p className="m-0 text-sm whitespace-pre-wrap">{feedbackText}</p>
                    </div>
                    <div>
                        <LemonButton
                            type="primary"
                            size="small"
                            onClick={openSupportModalWithPrefill}
                            disabledReason={hasSubmittedTicket ? 'Ticket already created' : undefined}
                        >
                            Review support ticket
                        </LemonButton>
                    </div>
                </div>
            </MessageTemplate>
            {supportModal}
        </>
    )
})
