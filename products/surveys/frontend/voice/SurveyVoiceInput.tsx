import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { SurveyRecordingProps, surveyRecordingLogic } from './surveyRecordingLogic'

export function SurveyVoiceInput(props: SurveyRecordingProps & { disabled?: boolean }): JSX.Element {
    const logic = surveyRecordingLogic(props)
    const { disabled } = props
    const { status, audioUrl, error } = useValues(logic)
    const { startRecording, stopRecording, discardRecording, transcribeRecording } = useActions(logic)
    return (
        <div className="space-y-2">
            <div className="text-xs text-secondary">
                Record up to one minute. Preview your recording before choosing to transcribe it. Review the transcript
                before sending your feedback.
            </div>
            {audioUrl && <audio controls src={audioUrl} className="w-full" />}
            <div className="flex flex-wrap gap-2">
                {status === 'idle' && (
                    <LemonButton
                        size="small"
                        type="secondary"
                        disabledReason={disabled ? 'Finish sending your feedback first' : undefined}
                        onClick={startRecording}
                        data-attr="survey-voice-record"
                    >
                        Record an answer
                    </LemonButton>
                )}
                {status === 'requesting' && <span role="status">Waiting for microphone permission…</span>}
                {status === 'recording' && (
                    <LemonButton
                        size="small"
                        type="primary"
                        onClick={stopRecording}
                        data-attr="survey-voice-stop-recording"
                    >
                        Stop recording
                    </LemonButton>
                )}
                {(status === 'ready' || status === 'transcribing') && (
                    <LemonButton
                        size="small"
                        type="primary"
                        loading={status === 'transcribing'}
                        disabledReason={disabled ? 'Finish sending your feedback first' : undefined}
                        onClick={transcribeRecording}
                        data-attr="survey-voice-transcribe"
                    >
                        Transcribe recording
                    </LemonButton>
                )}
                {status !== 'idle' && (
                    <LemonButton size="small" onClick={discardRecording} data-attr="survey-voice-discard-recording">
                        Discard recording
                    </LemonButton>
                )}
            </div>
            {status === 'recording' && (
                <div role="status" className="text-xs">
                    Recording your answer. Recording stops after one minute.
                </div>
            )}
            {error && (
                <div role="alert" className="text-danger text-sm">
                    {error}
                </div>
            )}
        </div>
    )
}
