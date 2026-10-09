import { useActions, useValues } from 'kea'
import { useRef, useState } from 'react'

import { IconThumbsDown, IconThumbsDownFilled, IconThumbsUp, IconThumbsUpFilled } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'

import { InboxReportFeedbackSentiment } from '../../inboxAnalytics'
import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { SignalReport } from '../../types'
import { ReportFeedbackBang } from './ReportFeedbackBang'

// Matches the cap on the sibling inbox dialogs (Dismiss, Refund, agent question); the note rides along as
// an analytics property, so keep it under the client's per-property limit.
const FEEDBACK_NOTE_MAX_LENGTH = 4000

function prefersReducedMotion(): boolean {
    return !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
}

/**
 * Thumbs rating at the end of the report body, where someone has just finished reading. The rating
 * submits on the first click, so there's no text field to mistake for the dismissal reason. Only
 * once it's recorded does an optional note appear, so the note can never gate the rating, and
 * ignoring it leaves the flow exactly as it was.
 */
export function ReportFeedbackFooter({
    report,
    align = 'start',
}: {
    report: SignalReport
    /** `end` pins the row to the right edge, for the redesign's summary column. */
    align?: 'start' | 'end'
}): JSX.Element {
    const logic = inboxReportDetailLogic({ reportId: report.id, report })
    const { feedbackSentiment, feedbackNoteOpen, feedbackNoteDraft, feedbackNoteSent, feedbackNoteSubmitting } =
        useValues(logic)
    const { rateReport, openFeedbackNote, setFeedbackNoteDraft, submitFeedbackNote } = useActions(logic)

    // Focus the note only when *this* instance opened it. `feedbackNoteOpen` is report-keyed state
    // shared with the copy of this row on the other tab, and `LemonTabs` remounts tab content, so
    // an unconditional `autoFocus` would grab focus and scroll on every tab switch with a draft open.
    const [openedHere, setOpenedHere] = useState(false)

    // The comic burst is view-only decoration, so it stays in local state: the rating itself is
    // report-keyed in the logic, and only the instance that was clicked should pop.
    const bangEnabled = useFeatureFlag('INBOX_REPORT_FEEDBACK_BANG')
    const thumbsUpRef = useRef<HTMLButtonElement>(null)
    const [bang, setBang] = useState<{ id: number; origin: { x: number; y: number } } | null>(null)

    const isPositive = feedbackSentiment === 'positive'
    const isNegative = feedbackSentiment === 'negative'
    // Re-clicking the chosen thumb is a no-op rather than a second identical feedback event.
    const rate = (sentiment: InboxReportFeedbackSentiment): void => {
        if (feedbackSentiment === sentiment) {
            return
        }
        rateReport(sentiment)
        if (sentiment === 'positive' && bangEnabled && !prefersReducedMotion() && thumbsUpRef.current) {
            const rect = thumbsUpRef.current.getBoundingClientRect()
            setBang({ id: Date.now(), origin: { x: rect.left + rect.width / 2, y: rect.top } })
        }
    }

    return (
        <div className={align === 'end' ? 'flex flex-col items-end gap-2 pt-1' : 'flex flex-col gap-2 pt-1'}>
            {/* `select-none` stays on the rating row: on the wrapper it would also cover the note
                textarea, where it blocks selecting text to edit or copy a draft. */}
            <div className="flex items-center gap-2 flex-wrap text-xs text-tertiary select-none">
                <span>{feedbackSentiment ? 'Thanks for the feedback' : 'Was this report useful?'}</span>
                <div className="flex items-center gap-1">
                    <LemonButton
                        ref={thumbsUpRef}
                        size="xsmall"
                        type={isPositive ? 'primary' : 'secondary'}
                        icon={isPositive ? <IconThumbsUpFilled /> : <IconThumbsUp />}
                        tooltip="Yes, this was useful"
                        aria-label="This report was useful"
                        aria-pressed={isPositive}
                        onClick={() => rate('positive')}
                        data-attr="inbox-report-feedback-thumbs-up"
                    />
                    <LemonButton
                        size="xsmall"
                        type={isNegative ? 'primary' : 'secondary'}
                        icon={isNegative ? <IconThumbsDownFilled /> : <IconThumbsDown />}
                        tooltip="No, this wasn't useful"
                        aria-label="This report was not useful"
                        aria-pressed={isNegative}
                        onClick={() => rate('negative')}
                        data-attr="inbox-report-feedback-thumbs-down"
                    />
                </div>
                {feedbackSentiment && !feedbackNoteOpen && !feedbackNoteSent && (
                    <LemonButton
                        size="xsmall"
                        type="tertiary"
                        onClick={() => {
                            setOpenedHere(true)
                            openFeedbackNote()
                        }}
                        data-attr="inbox-report-feedback-add-note"
                    >
                        Add a note
                    </LemonButton>
                )}
                {feedbackNoteSent && <span>Note added</span>}
            </div>
            {bang && <ReportFeedbackBang key={bang.id} origin={bang.origin} onDone={() => setBang(null)} />}
            {feedbackNoteOpen && (
                <div className="flex w-full max-w-prose flex-col items-start gap-2">
                    <LemonTextArea
                        value={feedbackNoteDraft}
                        onChange={setFeedbackNoteDraft}
                        placeholder="What was useful or off?"
                        // The placeholder is the only visible prompt and it disappears on the first
                        // keystroke, so the field carries its own name for screen readers.
                        aria-label="Add a note about this report"
                        maxLength={FEEDBACK_NOTE_MAX_LENGTH}
                        minRows={5}
                        maxRows={12}
                        autoFocus={openedHere}
                        className="w-full"
                        data-attr="inbox-report-feedback-note"
                    />
                    <LemonButton
                        size="xsmall"
                        type="primary"
                        loading={feedbackNoteSubmitting}
                        disabledReason={feedbackNoteDraft.trim() ? undefined : 'Write a note first'}
                        onClick={() => submitFeedbackNote(feedbackNoteDraft)}
                        data-attr="inbox-report-feedback-note-send"
                    >
                        Send
                    </LemonButton>
                </div>
            )}
        </div>
    )
}
