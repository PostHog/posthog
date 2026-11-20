import { requireOptionalNativeModule } from 'expo'
import { getLocales } from 'expo-localization'
import type { ExpoSpeechRecognitionErrorCode, ExpoSpeechRecognitionModule } from 'expo-speech-recognition'
import { useCallback, useLayoutEffect, useRef, useState } from 'react'
import { AppState, Platform } from 'react-native'

import { chatDictationPhrases } from './chatDictationPhrases'

type Phase = 'idle' | 'starting' | 'listening' | 'finishing'
type SpeechRecognition = typeof ExpoSpeechRecognitionModule
type Options = {
    onTranscript: (transcript: string) => void
    disabled?: boolean
    scopeKey: string | number
    draftText?: string
}
type Dictation = {
    available: boolean
    phase: Phase
    preview: string
    error: string | null
    toggle: () => void
    cancel: () => void
    isActive: () => boolean
}

type Session = {
    cancelNative?: () => void
    stop?: () => void
    requestingPermission?: boolean
    resumeAfterPermission?: () => void
}

const unavailable = 'On-device dictation is unavailable on this device.'
const unsupportedLanguage = 'On-device dictation is unavailable for your device language.'
const microphoneDenied = 'Allow microphone access in Settings to use dictation.'
const recognitionFailed = 'Dictation stopped unexpectedly. Try again.'
const noSpeech = 'No speech detected. Try again.'
const startTimeout = 8000
const finishTimeout = 2500
const listeningInactivityTimeout = 60000
const permissionReturnTimeout = 1500

// The native module broadcasts events without a session identifier.
let nativeSession: Session | null = null

function getRecognizer(): SpeechRecognition | null {
    if (Platform.OS !== 'ios' && (Platform.OS !== 'android' || Number(Platform.Version) < 33)) {
        return null
    }
    return requireOptionalNativeModule<SpeechRecognition>('ExpoSpeechRecognition')
}

function errorMessage(code: ExpoSpeechRecognitionErrorCode): string {
    switch (code) {
        case 'not-allowed':
            return microphoneDenied
        case 'language-not-supported':
            return unsupportedLanguage
        case 'service-not-allowed':
        case 'network':
            return unavailable
        case 'no-speech':
        case 'speech-timeout':
            return noSpeech
        default:
            return recognitionFailed
    }
}

function localeBaseName(locale: string): string {
    const base = locale.replaceAll('_', '-').replace(/-[a-z0-9](?:-|$).*$/i, '')
    try {
        return (Intl.getCanonicalLocales?.(base)[0] ?? base).toLowerCase()
    } catch {
        return base.toLowerCase()
    }
}

function installedLocale(languageTag: string, installedLocales: string[]): string | undefined {
    const base = localeBaseName(languageTag)
    const language = base.split('-', 1)[0]
    return (
        installedLocales.find((locale) => localeBaseName(locale) === base) ??
        installedLocales.find((locale) => localeBaseName(locale) === language)
    )
}

export function useChatDictation({ onTranscript, disabled = false, scopeKey, draftText = '' }: Options): Dictation {
    const [recognizer] = useState(getRecognizer)
    const [phase, setPhase] = useState<Phase>('idle')
    const [preview, setPreview] = useState('')
    const [error, setError] = useState<string | null>(null)
    const session = useRef<Session | null>(null)
    const foreground = useRef(AppState.currentState !== 'background')
    const onTranscriptRef = useRef(onTranscript)
    const draftTextRef = useRef(draftText)

    useLayoutEffect(() => {
        onTranscriptRef.current = onTranscript
        draftTextRef.current = draftText
    }, [draftText, onTranscript])

    const abandon = useCallback((): void => {
        const current = session.current
        session.current = null
        current?.resumeAfterPermission?.()
        current?.cancelNative?.()
    }, [])

    const cancel = useCallback((): void => {
        abandon()
        setPhase('idle')
        setPreview('')
        setError(null)
    }, [abandon])

    // biome-ignore lint/correctness/useExhaustiveDependencies: A change of chat or eligibility cancels the active session.
    useLayoutEffect(() => {
        cancel()
        return abandon
    }, [abandon, cancel, disabled, scopeKey])

    useLayoutEffect(() => {
        const subscription = AppState.addEventListener('change', (state) => {
            foreground.current = state !== 'background'
            if (state === 'active') {
                session.current?.resumeAfterPermission?.()
            } else if (state === 'background' && !session.current?.requestingPermission) {
                cancel()
            }
        })
        return () => subscription.remove()
    }, [cancel])

    const isActive = useCallback((): boolean => session.current !== null, [])

    const toggle = useCallback((): void => {
        if (disabled || !recognizer) {
            return
        }
        if (session.current) {
            if (session.current.stop) {
                session.current.stop()
            } else {
                cancel()
            }
            return
        }
        if (!foreground.current) {
            return
        }

        const current: Session = {}
        session.current = current
        setPhase('starting')
        setError(null)

        const finish = (message: string | null, transcript?: string): void => {
            if (session.current !== current) {
                return
            }
            session.current = null
            setPhase('idle')
            setPreview('')
            setError(message)
            if (transcript) {
                onTranscriptRef.current(transcript)
            }
        }

        const start = async (): Promise<void> => {
            try {
                if (
                    !recognizer.supportsOnDeviceRecognition() ||
                    (Platform.OS === 'ios' && !recognizer.isRecognitionAvailable())
                ) {
                    finish(unavailable)
                    return
                }
                const languageTag = getLocales()[0]?.languageTag
                const { installedLocales } = await recognizer.getSupportedLocales({})
                if (session.current !== current) {
                    return
                }
                const lang = languageTag && installedLocale(languageTag, installedLocales)
                if (!lang) {
                    finish(unsupportedLanguage)
                    return
                }
                let permission = await recognizer.getMicrophonePermissionsAsync()
                if (session.current !== current) {
                    return
                }
                if (!permission.granted && permission.canAskAgain) {
                    // Android can report background while the system permission dialog owns the foreground.
                    current.requestingPermission = Platform.OS === 'android'
                    permission = await recognizer.requestMicrophonePermissionsAsync()
                    if (session.current !== current) {
                        return
                    }
                }
                if (!permission.granted) {
                    finish(microphoneDenied)
                    return
                }
                if (current.requestingPermission && !foreground.current) {
                    await new Promise<void>((resolve) => {
                        const timer = setTimeout(resolve, permissionReturnTimeout)
                        current.resumeAfterPermission = () => {
                            clearTimeout(timer)
                            resolve()
                        }
                    })
                    current.resumeAfterPermission = undefined
                }
                current.requestingPermission = false
                if (session.current !== current) {
                    return
                }
                if (!foreground.current) {
                    finish(null)
                    return
                }
                if (nativeSession) {
                    finish('Dictation is still stopping. Try again.')
                    return
                }

                const subscriptions: { remove: () => void }[] = []
                let watchdog: ReturnType<typeof setTimeout> | undefined
                const release = (): void => {
                    clearTimeout(watchdog)
                    for (const subscription of subscriptions) {
                        subscription.remove()
                    }
                    if (nativeSession === current) {
                        nativeSession = null
                    }
                }
                let finalTranscript = ''
                let partialTranscript = ''
                let failure: string | null = null
                let started = false
                let startFailed = false
                let stopping = false
                let aborted = false

                const abort = (): void => {
                    if (aborted) {
                        return
                    }
                    aborted = true
                    clearTimeout(watchdog)
                    try {
                        recognizer.abort()
                    } catch {
                        // Check if the native service has torn down below.
                    }
                    // Normally abort emits end. If the service omits it, wait for teardown before accepting a new session.
                    if (nativeSession === current) {
                        watchdog = setTimeout(() => {
                            void recognizer.getStateAsync().then(
                                (state) => {
                                    if (state === 'inactive' && nativeSession === current) {
                                        release()
                                    }
                                },
                                () => {}
                            )
                        }, finishTimeout)
                    }
                }

                const complete = (): void => {
                    const transcript = partialTranscript || finalTranscript.trim()
                    if (!failure || failure === noSpeech) {
                        finish(transcript ? null : noSpeech, transcript)
                    } else {
                        finish(failure)
                    }
                }

                const awaitSpeech = (): void => {
                    if (!stopping && current.stop) {
                        clearTimeout(watchdog)
                        watchdog = setTimeout(current.stop, listeningInactivityTimeout)
                    }
                }

                const awaitEnd = (): void => {
                    clearTimeout(watchdog)
                    watchdog = setTimeout(() => {
                        complete()
                        abort()
                    }, finishTimeout)
                }

                nativeSession = current
                // iOS starts asynchronously. Abort once the native start arrives so it cannot open the mic after abort.
                current.cancelNative = () => {
                    clearTimeout(watchdog)
                    finalTranscript = ''
                    partialTranscript = ''
                    if (started || startFailed || Platform.OS === 'android') {
                        abort()
                    }
                }
                watchdog = setTimeout(() => {
                    finish(recognitionFailed)
                    current.cancelNative?.()
                }, startTimeout)

                try {
                    subscriptions.push(
                        recognizer.addListener('start', () => {
                            started = true
                            if (session.current !== current) {
                                abort()
                                return
                            }
                            current.stop = () => {
                                if (!stopping) {
                                    stopping = true
                                    setPhase('finishing')
                                    awaitEnd()
                                    try {
                                        recognizer.stop()
                                    } catch {
                                        // The watchdog finishes the attempt and tears down the recognizer.
                                    }
                                }
                            }
                            awaitSpeech()
                            setPhase('listening')
                        }),
                        recognizer.addListener('result', (event) => {
                            if (session.current !== current || failure) {
                                return
                            }
                            const transcript = event.results[0]?.transcript
                            if (transcript?.trim()) {
                                // iOS prefixes successive final segments with a space.
                                if (event.isFinal) {
                                    finalTranscript = transcript.startsWith(' ')
                                        ? finalTranscript + transcript
                                        : transcript
                                    partialTranscript = ''
                                    setPreview(finalTranscript.trim())
                                    setPhase('finishing')
                                    stopping = true
                                    awaitEnd()
                                } else if (!finalTranscript || transcript.startsWith(' ')) {
                                    partialTranscript = (finalTranscript + transcript).trim()
                                    awaitSpeech()
                                    setPreview(partialTranscript)
                                }
                            }
                        }),
                        recognizer.addListener('error', ({ error: code }) => {
                            if (!started && code !== 'aborted') {
                                startFailed = true
                            }
                            if (session.current !== current) {
                                if (startFailed) {
                                    abort()
                                }
                                return
                            }
                            failure = errorMessage(code)
                            if (failure !== noSpeech) {
                                setPreview('')
                            }
                            setPhase('finishing')
                            stopping = true
                            awaitEnd()
                        }),
                        recognizer.addListener('end', () => {
                            release()
                            complete()
                        })
                    )
                    recognizer.start({
                        lang,
                        interimResults: true,
                        continuous: false,
                        maxAlternatives: 1,
                        requiresOnDeviceRecognition: true,
                        contextualStrings: chatDictationPhrases(draftTextRef.current),
                        addsPunctuation: true,
                        recordingOptions: { persist: false },
                    })
                } catch {
                    release()
                    finish(recognitionFailed)
                }
            } catch {
                finish(recognitionFailed)
            }
        }
        void start()
    }, [cancel, disabled, recognizer])

    return { available: recognizer !== null, phase, preview, error, toggle, cancel, isActive }
}
