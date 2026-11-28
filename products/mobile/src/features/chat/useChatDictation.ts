import { requireOptionalNativeModule } from 'expo'
import { getLocales } from 'expo-localization'
import type { ExpoSpeechRecognitionErrorCode, ExpoSpeechRecognitionModule } from 'expo-speech-recognition'
import { useCallback, useLayoutEffect, useRef, useState } from 'react'
import { AppState, Platform } from 'react-native'

import { track } from '@/lib/analytics'

import { chatDictationPhrases } from './chatDictationPhrases'

type Phase = 'idle' | 'starting' | 'listening' | 'finishing'
type SpeechRecognition = typeof ExpoSpeechRecognitionModule
type Options = {
    onTranscript: (transcript: string) => void
    composer: 'tasks' | 'classic'
    disabled?: boolean
    startDisabled?: boolean
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
const scriptSubtag = /^[a-z]{4}$/

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

function speechLocaleKey(base: string): string {
    const [language, subtag = ''] = base.split('-')
    if (language !== 'zh' || scriptSubtag.test(subtag)) {
        return base
    }
    // Hermes lacks Intl.Locale. Use the CLDR defaults for Chinese speech models without a script tag.
    const script = ['hk', 'mo', 'tw'].includes(subtag) ? 'hant' : 'hans'
    return `zh-${script}${base.slice(2)}`
}

function installedLocale(languageTag: string, installedLocales: string[]): string | undefined {
    const preference = localeBaseName(languageTag)
    const key = speechLocaleKey(preference)
    const [language, subtag] = key.split('-')
    const languageAndScript = scriptSubtag.test(subtag ?? '') ? `${language}-${subtag}` : language
    const models = installedLocales.map((locale) => {
        const base = localeBaseName(locale)
        return { locale, base, key: speechLocaleKey(base) }
    })
    return (
        models.find((model) => model.base === preference) ??
        models.find((model) => model.key === key) ??
        models.find((model) => model.key === languageAndScript)
    )?.locale
}

export function useChatDictation({
    onTranscript,
    composer,
    disabled = false,
    startDisabled = false,
    scopeKey,
    draftText = '',
}: Options): Dictation {
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
        if (!current) {
            return
        }
        session.current = null
        current.resumeAfterPermission?.()
        current.cancelNative?.()
        track('mobile_chat_dictation_finished', { composer, outcome: 'cancelled' })
    }, [composer])

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
        if (startDisabled || !foreground.current) {
            return
        }

        const current: Session = {}
        session.current = current
        setPhase('starting')
        setError(null)
        track('mobile_chat_dictation_started', { composer })

        const finish = (message: string | null, transcript?: string): void => {
            if (session.current !== current) {
                return
            }
            session.current = null
            setPhase('idle')
            setPreview('')
            setError(message)
            track('mobile_chat_dictation_finished', {
                composer,
                outcome: transcript ? 'transcribed' : message ? 'failed' : 'cancelled',
            })
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
                let abortedBeforeIosStart = false
                const waitingForIosStart = (): boolean => Platform.OS === 'ios' && !started && !startFailed

                const watchForTeardown = (): void => {
                    if (nativeSession !== current) {
                        return
                    }
                    const probe = setTimeout(async () => {
                        let inactive: boolean
                        try {
                            inactive = (await recognizer.getStateAsync()) === 'inactive'
                        } catch {
                            inactive = false
                        }
                        if (nativeSession !== current || watchdog !== probe) {
                            return
                        }
                        if (inactive) {
                            release()
                        } else {
                            watchForTeardown()
                        }
                    }, finishTimeout)
                    watchdog = probe
                }

                const abort = (retryAfterLateStart = false): void => {
                    if (nativeSession !== current || (aborted && !retryAfterLateStart)) {
                        return
                    }
                    aborted = true
                    abortedBeforeIosStart ||= waitingForIosStart()
                    clearTimeout(watchdog)
                    try {
                        recognizer.abort()
                    } catch {
                        // Check if the native service has torn down below.
                    }
                    watchForTeardown()
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
                current.cancelNative = () => {
                    finalTranscript = ''
                    partialTranscript = ''
                    abort()
                }
                watchdog = setTimeout(() => {
                    finish(recognitionFailed)
                    abort()
                }, startTimeout)

                try {
                    subscriptions.push(
                        recognizer.addListener('start', () => {
                            const retryAfterLateStart = abortedBeforeIosStart && !started
                            started = true
                            if (session.current !== current) {
                                abort(retryAfterLateStart)
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
                            // An early iOS abort can emit end before the queued start opens the mic.
                            if (!abortedBeforeIosStart) {
                                release()
                                complete()
                            }
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
    }, [cancel, composer, disabled, recognizer, startDisabled])

    return { available: recognizer !== null, phase, preview, error, toggle, cancel, isActive }
}
