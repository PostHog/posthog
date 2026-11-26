import { useValues } from 'kea'
import { useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { lemonBannerLogic } from 'lib/lemon-ui/LemonBanner/lemonBannerLogic'
import { Popover } from 'lib/lemon-ui/Popover'

import { FeaturePreviewFeedbackBanner } from 'products/workflows/frontend/FeaturePreviewFeedbackBanner'

// The api-type survey the new editor's feedback reports to.
const EMAIL_EDITOR_FEEDBACK_SURVEY_ID = '01a1b1b8-80ac-0000-69c3-d6d49770d78c'
const EMAIL_EDITOR_FEEDBACK_RATING_QUESTION_ID = '7083646e-1fba-4ad7-97ee-e290849ac4fe'
const EMAIL_EDITOR_FEEDBACK_TEXT_QUESTION_ID = 'e49fca42-fae0-4f4e-9c26-f9b0517aed45'
const DISMISS_KEY = 'workflows-email-editor-feedback-popover'

export function EmailEditorFeedback(): JSX.Element | null {
    const [open, setOpen] = useState(false)
    // Closing the prompt hides it for good, so the button goes too rather than open an empty popover.
    const { isDismissed } = useValues(lemonBannerLogic({ dismissKey: DISMISS_KEY }))
    if (isDismissed) {
        return null
    }
    return (
        <Popover
            visible={open}
            onClickOutside={() => setOpen(false)}
            placement="bottom-end"
            overlay={
                <div className="w-96">
                    <FeaturePreviewFeedbackBanner
                        surveyId={EMAIL_EDITOR_FEEDBACK_SURVEY_ID}
                        ratingQuestionId={EMAIL_EDITOR_FEEDBACK_RATING_QUESTION_ID}
                        feedbackQuestionId={EMAIL_EDITOR_FEEDBACK_TEXT_QUESTION_ID}
                        surface="email-editor"
                        dismissKey={DISMISS_KEY}
                        prompt="This email editor is new. Is it doing what you need?"
                        feedbackTitle="Help shape the email editor"
                        feedbackPlaceholder="Tell us what works, what doesn't, or what you'd change"
                        className="m-0"
                        data-attr="email-editor-feedback"
                    />
                </div>
            }
        >
            <LemonButton
                size="xsmall"
                active={open}
                onClick={() => setOpen(!open)}
                data-attr="email-editor-feedback-open"
            >
                Feedback
            </LemonButton>
        </Popover>
    )
}
