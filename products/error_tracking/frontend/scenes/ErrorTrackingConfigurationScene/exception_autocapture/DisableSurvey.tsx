import { useActions, useValues } from 'kea'

import { LemonButton, LemonTextArea } from '@posthog/lemon-ui'

import { disableSurveyLogic } from './disableSurveyLogic'

export function DisableSurvey(): JSX.Element | null {
    const { visible, response, submitted } = useValues(disableSurveyLogic)
    const { setResponse, submitResponse } = useActions(disableSurveyLogic)

    if (!visible) {
        return null
    }

    return (
        <div className="mt-4 max-w-lg border rounded-lg p-4 bg-bg-light">
            {submitted ? (
                <p className="font-medium text-success m-0">Thanks for your feedback!</p>
            ) : (
                <div className="flex flex-col gap-3">
                    <p className="font-medium m-0">
                        Do you mind telling us why are you disabling exception autocapture?
                    </p>
                    <LemonTextArea
                        placeholder="Share your feedback..."
                        value={response}
                        onChange={setResponse}
                        rows={3}
                    />
                    <div>
                        <LemonButton
                            type="primary"
                            size="small"
                            disabledReason={!response.trim() ? 'Please enter some feedback' : undefined}
                            onClick={submitResponse}
                        >
                            Submit
                        </LemonButton>
                    </div>
                </div>
            )}
        </div>
    )
}
