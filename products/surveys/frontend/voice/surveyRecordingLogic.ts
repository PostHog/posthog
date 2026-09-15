import {
    LogicWrapper,
    MakeLogicType,
    actions,
    beforeUnmount,
    getContext,
    kea,
    key,
    listeners,
    path,
    props,
    reducers,
} from 'kea'

export type RecordingStatus = 'idle' | 'requesting' | 'recording' | 'ready' | 'transcribing'

export interface SurveyRecordingProps {
    id: string
    onTranscript: (text: string) => void
    onStatusChange?: (status: RecordingStatus) => void
    transcribe: (audio: Blob, signal: AbortSignal) => Promise<string>
}

export interface surveyRecordingLogicValues {
    status: RecordingStatus
    error: string
    audioUrl: string
}

export interface surveyRecordingLogicActions {
    startRecording: () => { value: true }
    stopRecording: () => { value: true }
    discardRecording: () => { value: true }
    transcribeRecording: () => { value: true }
    setStatus: (status: RecordingStatus) => { status: RecordingStatus }
    setError: (error: string) => { error: string }
    setAudioUrl: (audioUrl: string) => { audioUrl: string }
}

export type surveyRecordingLogicType = MakeLogicType<
    surveyRecordingLogicValues,
    surveyRecordingLogicActions,
    SurveyRecordingProps
>

export const surveyRecordingLogic: LogicWrapper<surveyRecordingLogicType> = kea<surveyRecordingLogicType>([
    props({} as SurveyRecordingProps),
    key(({ id }) => id),
    path((key) => ['products', 'surveys', 'frontend', 'voice', 'surveyRecordingLogic', key]),
    actions({
        startRecording: true,
        stopRecording: true,
        discardRecording: true,
        transcribeRecording: true,
        setStatus: (status: RecordingStatus) => ({ status }),
        setError: (error: string) => ({ error }),
        setAudioUrl: (audioUrl: string) => ({ audioUrl }),
    }),
    reducers({
        status: ['idle' as RecordingStatus, { setStatus: (_, { status }) => status }],
        error: ['', { setError: (_, { error }) => error }],
        audioUrl: ['', { setAudioUrl: (_, { audioUrl }) => audioUrl }],
    }),
    listeners(({ actions, values, props, cache }) => ({
        setStatus: ({ status }) => props.onStatusChange?.(status),
        startRecording: async () => {
            if (values.status !== 'idle') {
                return
            }
            actions.setStatus('requesting')
            actions.setError('')
            const manager = cache.disposables
            const context = getContext()
            let canceled = false
            let stream: MediaStream | undefined
            let recorder: MediaRecorder | undefined
            let timer: ReturnType<typeof setTimeout> | undefined
            manager.add(
                () => () => {
                    canceled = true
                    if (timer) {
                        clearTimeout(timer)
                    }
                    if (recorder) {
                        recorder.onstop = null
                        recorder.ondataavailable = null
                        recorder.onerror = null
                        if (recorder.state !== 'inactive') {
                            recorder.stop()
                        }
                    }
                    stream?.getTracks().forEach((track) => track.stop())
                    cache.recorder = undefined
                },
                'microphone',
                { pauseOnPageHidden: false }
            )
            try {
                const mimeType = ['audio/webm', 'audio/mp4', 'audio/ogg'].find((type) =>
                    MediaRecorder.isTypeSupported(type)
                )
                if (!mimeType) {
                    throw new Error('unsupported')
                }
                stream = await navigator.mediaDevices.getUserMedia({ audio: true })
                if (canceled || manager.isDisposed || getContext() !== context) {
                    stream.getTracks().forEach((track) => track.stop())
                    return
                }
                recorder = new MediaRecorder(stream, { mimeType, audioBitsPerSecond: 64_000 })
                cache.recorder = recorder
                const chunks: Blob[] = []
                recorder.ondataavailable = ({ data }) => {
                    if (data.size) {
                        chunks.push(data)
                    }
                }
                recorder.onstop = () => {
                    if (canceled || manager.isDisposed || getContext() !== context) {
                        return
                    }
                    const audio = new Blob(chunks, { type: mimeType })
                    manager.dispose('microphone')
                    if (!audio.size || audio.size > 5 * 1024 * 1024) {
                        actions.setStatus('idle')
                        actions.setError('Couldn’t use this recording. Try again or type your feedback.')
                        return
                    }
                    cache.audio = audio
                    const url = URL.createObjectURL(audio)
                    manager.add(
                        () => () => {
                            URL.revokeObjectURL(url)
                            cache.audio = undefined
                        },
                        'audio',
                        { pauseOnPageHidden: false }
                    )
                    actions.setAudioUrl(url)
                    actions.setStatus('ready')
                }
                recorder.onerror = () => {
                    if (canceled || manager.isDisposed || getContext() !== context) {
                        return
                    }
                    manager.dispose('microphone')
                    actions.setStatus('idle')
                    actions.setError('Recording stopped unexpectedly. Try again or type your feedback.')
                }
                recorder.start()
                timer = setTimeout(() => {
                    if (!canceled && !manager.isDisposed && getContext() === context) {
                        actions.stopRecording()
                    }
                }, 60_000)
                actions.setStatus('recording')
            } catch {
                if (canceled || manager.isDisposed || getContext() !== context) {
                    return
                }
                manager.dispose('microphone')
                actions.setStatus('idle')
                actions.setError('Couldn’t access your microphone. Check its permission or type your feedback.')
            }
        },
        stopRecording: () => {
            const recorder = cache.recorder as MediaRecorder | undefined
            if (recorder?.state === 'recording') {
                recorder.stop()
            }
        },
        discardRecording: () => {
            cache.disposables.dispose('upload')
            cache.disposables.dispose('microphone')
            cache.disposables.dispose('audio')
            actions.setAudioUrl('')
            actions.setError('')
            actions.setStatus('idle')
        },
        transcribeRecording: async () => {
            const audio = cache.audio as Blob | undefined
            if (values.status !== 'ready' || !audio) {
                return
            }
            const manager = cache.disposables
            const context = getContext()
            const controller = new AbortController()
            manager.add(() => () => controller.abort(), 'upload', { pauseOnPageHidden: false })
            actions.setStatus('transcribing')
            actions.setError('')
            try {
                const text = await props.transcribe(audio, controller.signal)
                if (controller.signal.aborted || manager.isDisposed || getContext() !== context) {
                    return
                }
                if (!text.trim()) {
                    throw new Error('empty transcript')
                }
                props.onTranscript(text)
                actions.discardRecording()
            } catch {
                if (controller.signal.aborted || manager.isDisposed || getContext() !== context) {
                    return
                }
                actions.setStatus('ready')
                actions.setError('Couldn’t transcribe your recording. Try again, or discard it and type your feedback.')
            }
        },
    })),
    beforeUnmount(({ props }) => props.onStatusChange?.('idle')),
])
