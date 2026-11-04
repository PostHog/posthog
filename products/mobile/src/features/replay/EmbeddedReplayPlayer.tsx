import * as Crypto from 'expo-crypto'
import { type ReactElement, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ActivityIndicator, AppState, Modal, Platform, Text, View } from 'react-native'
import { SafeAreaProvider, SafeAreaView } from 'react-native-safe-area-context'
import WebView, { type WebViewMessageEvent } from 'react-native-webview'

import { fetchReplayBlock, fetchReplaySources, ReplayByteBudget, type ReplaySources } from '@/api/replayPlayback'
import { sessionGeneration } from '@/auth/tokens'
import { useProjectScope } from '@/auth/useProjectScope'
import { reportScopeError } from '@/features/views/useViewsAccess'
import { actionErrorMessage } from '@/lib/errors'
import { CloseIcon } from '@/ui/icons/CloseIcon'
import { WarningIcon } from '@/ui/icons/WarningIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { StateView } from '@/ui/StateView'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, layout, type } from '@/ui/tokens'

import {
    blockChunkScript,
    blockStatusScript,
    cancelBlocksScript,
    parsePlayerMessage,
    playerHtml,
} from './player/playerHtml'

const PLAYER_ORIGIN = 'https://mobile-replay.invalid/'
const CHUNK_CHARACTERS = 64 * 1024

function isPlayerUrl(url: string): boolean {
    return url === PLAYER_ORIGIN || url === PLAYER_ORIGIN.slice(0, -1) || url === 'about:blank'
}

interface EmbeddedReplayPlayerProps {
    sessionId: string
    seconds: number
    startedAt: string | null
    onClose: () => void
}

interface PlayerBridge {
    controller: AbortController
    inFlight: Set<number>
    budget: ReplayByteBudget
    generation: number
    ready: boolean
    startupTimer: ReturnType<typeof setTimeout> | null
}

function clearStartupTimeout(current: PlayerBridge): void {
    if (current.startupTimer !== null) clearTimeout(current.startupTimer)
    current.startupTimer = null
}

export function EmbeddedReplayPlayer(props: EmbeddedReplayPlayerProps): ReactElement {
    const [attempt, setAttempt] = useState(0)
    return (
        <Modal
            visible
            presentationStyle="fullScreen"
            animationType="slide"
            supportedOrientations={['portrait', 'landscape']}
            onRequestClose={props.onClose}
        >
            <SafeAreaProvider>
                <PlayerContent key={attempt} {...props} onRetry={() => setAttempt((value) => value + 1)} />
            </SafeAreaProvider>
        </Modal>
    )
}

function PlayerContent({
    sessionId,
    seconds,
    startedAt,
    onClose,
    onRetry,
}: EmbeddedReplayPlayerProps & { onRetry: () => void }): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const scope = useProjectScope()
    const generation = sessionGeneration()
    const webview = useRef<WebView>(null)
    const [sources, setSources] = useState<ReplaySources | null>(null)
    const [failure, setFailure] = useState<string | null>(null)
    const [loading, setLoading] = useState(true)
    const [nonce] = useState(() => Crypto.randomUUID())
    const [initial] = useState(() => ({ seconds, startedAt, colors }))
    const bridge = useRef<PlayerBridge | null>(null)

    const isCurrent = useCallback(
        (current: PlayerBridge): boolean =>
            bridge.current === current &&
            !current.controller.signal.aborted &&
            current.generation === sessionGeneration(),
        []
    )
    const fail = useCallback(
        (message: string): void => {
            const current = bridge.current
            if (!current || !isCurrent(current)) return
            clearStartupTimeout(current)
            webview.current?.injectJavaScript(cancelBlocksScript())
            current.controller.abort()
            setFailure(message)
        },
        [isCurrent]
    )
    const resumeStartupTimeout = useCallback(
        (current: PlayerBridge): void => {
            clearStartupTimeout(current)
            if (!isCurrent(current) || current.ready || current.inFlight.size > 0) return
            current.startupTimer = setTimeout(() => {
                if (isCurrent(current)) fail('The player took too long to start. Try again.')
            }, 30_000)
        },
        [fail, isCurrent]
    )

    useEffect(() => {
        const controller = new AbortController()
        const current: PlayerBridge = {
            controller,
            inFlight: new Set(),
            budget: new ReplayByteBudget(),
            generation,
            ready: false,
            startupTimer: null,
        }
        bridge.current = current
        setSources(null)
        setFailure(null)
        setLoading(true)
        if (!scope) return () => controller.abort()
        void fetchReplaySources(sessionId, controller.signal)
            .then((data) => {
                if (isCurrent(current)) {
                    setSources(data)
                    resumeStartupTimeout(current)
                }
            })
            .catch((error: unknown) => {
                if (isCurrent(current)) {
                    reportScopeError(error, 'replay')
                    fail(actionErrorMessage(error))
                }
            })
        return () => {
            clearStartupTimeout(current)
            if (bridge.current === current) {
                webview.current?.injectJavaScript(cancelBlocksScript())
                bridge.current = null
            }
            controller.abort()
        }
    }, [sessionId, scope, generation, fail, isCurrent, resumeStartupTimeout])

    useEffect(() => {
        const subscription = AppState.addEventListener('change', (state) => {
            if (state !== 'active') webview.current?.injectJavaScript('window.__pauseReplay?.();true;')
        })
        return () => subscription.remove()
    }, [])

    const loadBlock = (current: PlayerBridge, id: number, index: number): void => {
        if (current.inFlight.has(id)) return
        const source = sources?.sources[index]
        if (!source) return
        current.inFlight.add(id)
        clearStartupTimeout(current)
        webview.current?.injectJavaScript(blockStatusScript(id, false))
        void fetchReplayBlock(sessionId, source, current.controller.signal, {
            budget: current.budget,
            onRequestState: (state) => {
                if (isCurrent(current)) {
                    webview.current?.injectJavaScript(blockStatusScript(id, state === 'loading'))
                }
            },
        })
            .then((text) => {
                if (!isCurrent(current)) return
                for (let offset = 0; offset < text.length || offset === 0; offset += CHUNK_CHARACTERS) {
                    webview.current?.injectJavaScript(
                        blockChunkScript(
                            id,
                            text.slice(offset, offset + CHUNK_CHARACTERS),
                            offset + CHUNK_CHARACTERS >= text.length
                        )
                    )
                }
            })
            .catch((error: unknown) => {
                if (isCurrent(current)) {
                    reportScopeError(error, 'replay')
                    fail(actionErrorMessage(error))
                }
            })
            .finally(() => {
                current.inFlight.delete(id)
                if (isCurrent(current)) resumeStartupTimeout(current)
            })
    }
    const onMessage = (event: WebViewMessageEvent): void => {
        if (!sources || !isPlayerUrl(event.nativeEvent.url)) return
        const message = parsePlayerMessage(event.nativeEvent.data, sources.sources.length)
        const current = bridge.current
        if (!message || !current || !isCurrent(current)) return
        if (message.type === 'ready') {
            current.ready = true
            clearStartupTimeout(current)
            setLoading(false)
            return
        }
        if (message.type === 'error') {
            fail(
                message.reason === 'no_full_snapshot'
                    ? "This recording doesn't contain a full screen snapshot to play."
                    : "Couldn't render this recording. Try again."
            )
            return
        }
        loadBlock(current, message.id, message.index)
    }
    const html = useMemo(
        () =>
            sources
                ? playerHtml(
                      {
                          sessionId,
                          seconds: initial.seconds,
                          startTimestamp: initial.startedAt ? new Date(initial.startedAt).getTime() : null,
                          blockCount: sources.sources.length,
                          replayProxyToken: sources.replay_proxy_token ?? null,
                      },
                      initial.colors,
                      nonce
                  )
                : null,
        [sources, sessionId, initial, nonce]
    )

    return (
        <SafeAreaView style={styles.screen} edges={['top', 'bottom', 'left', 'right']}>
            <View style={styles.header}>
                <Text style={styles.title} accessibilityRole="header">
                    Session replay
                </Text>
                <Pressable44
                    onPress={onClose}
                    accessibilityLabel="Close replay"
                    style={styles.close}
                    testID="replay-player-close"
                >
                    <CloseIcon size={iconSizes.control} />
                </Pressable44>
            </View>
            <View style={styles.body}>
                {failure ? (
                    <StateView
                        icon={<WarningIcon color={colors.tertiary} />}
                        title="Couldn't play this recording"
                        message={failure}
                        actionLabel="Try again"
                        onAction={onRetry}
                        testID="replay-player-error"
                    />
                ) : Platform.OS === 'web' ? (
                    <StateView
                        title="Playback is available in the mobile app"
                        message="Open this session on iOS or Android."
                    />
                ) : (
                    <>
                        {html ? (
                            <WebView
                                ref={webview}
                                source={{ html, baseUrl: PLAYER_ORIGIN }}
                                originWhitelist={['*']}
                                onShouldStartLoadWithRequest={(request) => isPlayerUrl(request.url)}
                                onMessage={onMessage}
                                onError={() => fail("Couldn't load the player. Try again.")}
                                onContentProcessDidTerminate={() => fail('The player stopped. Try again.')}
                                onRenderProcessGone={() => fail('The player stopped. Try again.')}
                                onOpenWindow={() => undefined}
                                allowFileAccess={false}
                                allowFileAccessFromFileURLs={false}
                                allowUniversalAccessFromFileURLs={false}
                                mixedContentMode="never"
                                javaScriptCanOpenWindowsAutomatically={false}
                                sharedCookiesEnabled={false}
                                thirdPartyCookiesEnabled={false}
                                incognito
                                javaScriptEnabled
                                scrollEnabled={false}
                                bounces={false}
                                setSupportMultipleWindows
                                style={styles.webview}
                                testID="replay-player-webview"
                            />
                        ) : null}
                        {loading ? (
                            <View
                                style={styles.loading}
                                accessibilityRole="progressbar"
                                accessibilityLabel="Loading recording"
                            >
                                <ActivityIndicator color={colors.tertiary} />
                                <Text style={styles.note}>Loading recording…</Text>
                            </View>
                        ) : null}
                    </>
                )}
            </View>
        </SafeAreaView>
    )
}

const useStyles = createStyles(({ colors }) => ({
    screen: { flex: 1, backgroundColor: colors.background },
    header: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        paddingHorizontal: layout.detailGutter,
        paddingVertical: 8,
    },
    title: { ...type.rowTitle, color: colors.ink },
    close: { padding: 10 },
    body: { flex: 1 },
    webview: { flex: 1, backgroundColor: colors.background },
    loading: {
        position: 'absolute',
        inset: 0,
        alignItems: 'center',
        justifyContent: 'center',
        gap: 12,
        backgroundColor: colors.background,
    },
    note: { ...type.meta, color: colors.secondary },
}))
