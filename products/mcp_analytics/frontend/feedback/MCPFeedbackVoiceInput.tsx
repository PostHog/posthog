import { BuiltLogic, useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { feedbackRecordingLogicType } from './feedbackRecordingLogic'

export function MCPFeedbackVoiceInput({
    logic,
    disabled,
}: {
    logic: BuiltLogic<feedbackRecordingLogicType>
    disabled: boolean
}): JSX.Element {
    const { status, audioUrl, error } = useValues(logic)
    const { startRecording, stopRecording, discardRecording, transcribeRecording } = useActions(logic)
    return (
        <div className="space-y-2">
            <div className="text-xs text-secondary">
                Record up to one minute. Your audio is sent for transcription. PostHog does not save the audio. Review
                the text before sending feedback.
            </div>
            {audioUrl && <audio controls src={audioUrl} className="w-full" />}
            <div className="flex flex-wrap gap-2">
                {status === 'idle' && (
                    <LemonButton
                        size="small"
                        type="secondary"
                        disabledReason={disabled ? 'Finish sending your feedback first' : undefined}
                        onClick={startRecording}
                        data-attr="mcp-feedback-record"
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
                        data-attr="mcp-feedback-stop-recording"
                    >
                        Stop recording
                    </LemonButton>
                )}
                {(status === 'ready' || status === 'transcribing') && (
                    <LemonButton
                        size="small"
                        type="primary"
                        loading={status === 'transcribing'}
                        onClick={transcribeRecording}
                        data-attr="mcp-feedback-transcribe"
                    >
                        Transcribe recording
                    </LemonButton>
                )}
                {status !== 'idle' && (
                    <LemonButton size="small" onClick={discardRecording} data-attr="mcp-feedback-discard-recording">
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
