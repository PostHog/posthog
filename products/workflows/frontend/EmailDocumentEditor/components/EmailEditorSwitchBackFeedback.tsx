import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { lemonBannerLogic } from 'lib/lemon-ui/LemonBanner/lemonBannerLogic'
import { Popover } from 'lib/lemon-ui/Popover'
import { uuid } from 'lib/utils/dom'

import { captureSurveyResponse } from 'products/workflows/frontend/surveyResponseCapture'

import { EmailEditorFeedbackNote } from './EmailEditorFeedbackNote'
import {
    EMAIL_EDITOR_FEEDBACK_SURVEY_ID,
    EMAIL_EDITOR_FEEDBACK_TEXT_QUESTION_ID,
    SWITCH_BACK_DISMISS_KEY,
} from './emailEditorFeedbackSurvey'
import { useEscapeToClose } from './useEscapeToClose'

/** On the old editor's bar: asks once why someone left the new editor. */
export function EmailEditorSwitchBackFeedback(): JSX.Element | null {
    const { isDismissed } = useValues(lemonBannerLogic({ dismissKey: SWITCH_BACK_DISMISS_KEY }))
    const { dismiss } = useActions(lemonBannerLogic({ dismissKey: SWITCH_BACK_DISMISS_KEY }))
    const [open, setOpen] = useState(false)
    useEscapeToClose(open, () => setOpen(false))
    if (isDismissed) {
        return null
    }
    const close = (): void => {
        setOpen(false)
        dismiss()
    }
    return (
        <Popover
            visible={open}
            onClickOutside={() => setOpen(false)}
            placement="bottom-start"
            overlay={
                <EmailEditorFeedbackNote
                    title="What made you switch back?"
                    placeholder="What was missing or didn't work in the new editor"
                    onCancel={close}
                    onSend={(note) => {
                        captureSurveyResponse({
                            surveyId: EMAIL_EDITOR_FEEDBACK_SURVEY_ID,
                            submissionId: uuid(),
                            completed: true,
                            answers: [
                                { questionIndex: 1, questionId: EMAIL_EDITOR_FEEDBACK_TEXT_QUESTION_ID, value: note },
                            ],
                            surface: 'email-editor-switch-back',
                        })
                        close()
                    }}
                />
            }
        >
            <LemonButton
                size="xsmall"
                type="tertiary"
                active={open}
                onClick={() => setOpen(!open)}
                data-attr="email-editor-switch-back-feedback"
            >
                Tell us why
            </LemonButton>
        </Popover>
    )
}
