import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'

import { mcpAnalyticsFeedbackAudioCreate } from '../generated/api'
import { feedbackRecordingLogic } from './feedbackRecordingLogic'

jest.mock('../generated/api', () => ({ mcpAnalyticsFeedbackAudioCreate: jest.fn() }))

describe('feedbackRecordingLogic', () => {
    let logic: ReturnType<typeof feedbackRecordingLogic.build>
    let unmount: () => void
    let stopTrack: jest.Mock
    let stream: MediaStream
    let recorder: {
        state: string
        ondataavailable: ((event: { data: Blob }) => void) | null
        onstop: (() => void) | null
        stop: jest.Mock
        start: jest.Mock
    }
    let onTranscript: jest.Mock

    beforeEach(() => {
        initKeaTests()
        stopTrack = jest.fn()
        stream = { getTracks: () => [{ stop: stopTrack }] } as unknown as MediaStream
        Object.defineProperty(navigator, 'mediaDevices', {
            configurable: true,
            value: { getUserMedia: jest.fn().mockResolvedValue(stream) },
        })
        recorder = {
            state: 'inactive',
            ondataavailable: null,
            onstop: null,
            start: jest.fn(() => {
                recorder.state = 'recording'
            }),
            stop: jest.fn(() => {
                recorder.state = 'inactive'
                recorder.ondataavailable?.({ data: new Blob(['audio'], { type: 'audio/webm' }) })
                recorder.onstop?.()
            }),
        }
        Object.defineProperty(global, 'MediaRecorder', {
            configurable: true,
            value: Object.assign(
                jest.fn(() => recorder),
                { isTypeSupported: () => true }
            ),
        })
        URL.createObjectURL = jest.fn(() => 'blob:example-recording')
        URL.revokeObjectURL = jest.fn()
        onTranscript = jest.fn()
        logic = feedbackRecordingLogic({ id: 'example-submission', onTranscript })
        unmount = logic.mount()
        jest.mocked(mcpAnalyticsFeedbackAudioCreate).mockReset()
        jest.mocked(mcpAnalyticsFeedbackAudioCreate).mockResolvedValue({ text: 'I found the failed call.' })
    })

    afterEach(() => {
        unmount()
        jest.restoreAllMocks()
    })

    it('keeps the recording local until transcription and lets a failed upload retry', async () => {
        expect(teamLogic.values.currentTeamId).toBeTruthy()
        await expectLogic(logic, () => {
            logic.actions.startRecording()
            logic.actions.startRecording()
        }).toFinishAllListeners()
        expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalledTimes(1)
        logic.actions.stopRecording()
        expect(stopTrack).toHaveBeenCalled()
        expect(logic.values.status).toBe('ready')
        expect(mcpAnalyticsFeedbackAudioCreate).not.toHaveBeenCalled()
        jest.mocked(mcpAnalyticsFeedbackAudioCreate).mockRejectedValueOnce(new Error('offline'))
        await expectLogic(logic, () => logic.actions.transcribeRecording()).toFinishAllListeners()
        expect(logic.values.status).toBe('ready')
        expect(logic.values.audioUrl).toBe('blob:example-recording')
        expect(onTranscript).not.toHaveBeenCalled()
        await expectLogic(logic, () => logic.actions.transcribeRecording()).toFinishAllListeners()
        expect(onTranscript).toHaveBeenCalledWith('I found the failed call.')
        expect(logic.values.status).toBe('idle')
        expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:example-recording')
    })

    it.each(['discard', 'unmount'] as const)('stops a microphone granted after %s', async (ending) => {
        let grant!: (stream: MediaStream) => void
        jest.mocked(navigator.mediaDevices.getUserMedia).mockReturnValue(
            new Promise((resolve) => {
                grant = resolve
            })
        )
        logic.actions.startRecording()
        expect(logic.values.status).toBe('requesting')
        if (ending === 'discard') {
            logic.actions.discardRecording()
        } else {
            unmount()
            unmount = () => {}
        }
        grant(stream)
        await expectLogic(logic).toFinishAllListeners()
        expect(stopTrack).toHaveBeenCalled()
        expect(recorder.start).not.toHaveBeenCalled()
        expect(onTranscript).not.toHaveBeenCalled()
    })

    it('ignores a transcription that arrives after navigation', async () => {
        await expectLogic(logic, () => logic.actions.startRecording()).toFinishAllListeners()
        logic.actions.stopRecording()
        let finish!: (result: { text: string }) => void
        jest.mocked(mcpAnalyticsFeedbackAudioCreate).mockReturnValue(
            new Promise((resolve) => {
                finish = resolve
            })
        )
        logic.actions.transcribeRecording()
        const signal = jest.mocked(mcpAnalyticsFeedbackAudioCreate).mock.calls[0][2]?.signal
        unmount()
        unmount = () => {}
        expect(signal?.aborted).toBe(true)
        finish({ text: 'Late transcript' })
        await expectLogic(logic).toFinishAllListeners()
        expect(onTranscript).not.toHaveBeenCalled()
        expect(URL.revokeObjectURL).toHaveBeenCalled()
    })
})
