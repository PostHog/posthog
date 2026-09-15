import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { surveyRecordingLogic } from './surveyRecordingLogic'

describe('surveyRecordingLogic', () => {
    let logic: ReturnType<typeof surveyRecordingLogic.build>
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
    let transcribe: jest.Mock

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
        transcribe = jest.fn().mockResolvedValue('I found what I needed.')
        logic = surveyRecordingLogic({ id: 'example-submission', onTranscript, transcribe })
        unmount = logic.mount()
    })

    afterEach(() => {
        unmount()
        jest.restoreAllMocks()
    })

    it.each(['failure', 'empty transcript'] as const)(
        'keeps the recording local and retries after %s',
        async (failure) => {
            await expectLogic(logic, () => {
                logic.actions.startRecording()
                logic.actions.startRecording()
            }).toFinishAllListeners()
            expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalledTimes(1)
            logic.actions.stopRecording()
            expect(stopTrack).toHaveBeenCalled()
            expect(logic.values.status).toBe('ready')
            expect(transcribe).not.toHaveBeenCalled()
            if (failure === 'failure') {
                transcribe.mockRejectedValueOnce(new Error('offline'))
            } else {
                transcribe.mockResolvedValueOnce('   ')
            }
            await expectLogic(logic, () => logic.actions.transcribeRecording()).toFinishAllListeners()
            expect(logic.values.status).toBe('ready')
            expect(logic.values.audioUrl).toBe('blob:example-recording')
            expect(onTranscript).not.toHaveBeenCalled()
            await expectLogic(logic, () => logic.actions.transcribeRecording()).toFinishAllListeners()
            expect(onTranscript).toHaveBeenCalledWith('I found what I needed.')
            expect(logic.values.status).toBe('idle')
            expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:example-recording')
        }
    )

    it('stops recording after one minute', async () => {
        jest.useFakeTimers()
        try {
            logic.actions.startRecording()
            await Promise.resolve()
            expect(logic.values.status).toBe('recording')
            jest.advanceTimersByTime(60_000)
            expect(logic.values.status).toBe('ready')
            expect(stopTrack).toHaveBeenCalled()
            expect(transcribe).not.toHaveBeenCalled()
        } finally {
            jest.useRealTimers()
        }
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
        let finish!: (text: string) => void
        transcribe.mockReturnValue(
            new Promise((resolve) => {
                finish = resolve
            })
        )
        logic.actions.transcribeRecording()
        const signal = transcribe.mock.calls[0][1]
        unmount()
        unmount = () => {}
        expect(signal?.aborted).toBe(true)
        finish('Late transcript')
        await expectLogic(logic).toFinishAllListeners()
        expect(onTranscript).not.toHaveBeenCalled()
        expect(URL.revokeObjectURL).toHaveBeenCalled()
    })
})
