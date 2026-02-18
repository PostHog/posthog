import { useActions, useValues } from 'kea'

import { IconX } from '@posthog/icons'
import { LemonButton, LemonTextArea } from '@posthog/lemon-ui'

import { disableSurveyLogic } from './disableSurveyLogic'

export function DisableSurvey(): JSX.Element | null {
    const { visible, response, submitted } = useValues(disableSurveyLogic)
    const { setResponse, submitResponse, hideSurvey } = useActions(disableSurveyLogic)

    if (!visible) {
        return null
    }

    return (
        <div className="mt-4 max-w-lg border rounded-lg p-4 bg-bg-light relative">
            <LemonButton
                icon={<IconX />}
                size="xsmall"
                noPadding
                onClick={hideSurvey}
                className="absolute top-3 right-3"
            />
            {submitted ? (
                <p className="font-medium text-success m-0">Thanks for your feedback!</p>
            ) : (
                <div className="space-y-3 pr-6">
                    <p className="font-medium m-0">Why are you disabling exception autocapture?</p>
                    <LemonTextArea
                        placeholder="Share your feedback..."
                        value={response}
                        onChange={setResponse}
                        rows={3}
                    />
                    <LemonButton
                        type="secondary"
                        size="small"
                        disabledReason={!response.trim() ? 'Please enter some feedback' : undefined}
                        onClick={submitResponse}
                    >
                        Submit
                    </LemonButton>
                </div>
            )}
        </div>
    )
}
