import * as Crypto from 'expo-crypto'
import { type ReactElement, useEffect, useMemo, useRef, useState } from 'react'
import { ActivityIndicator, AppState, Modal, Platform, Text, View } from 'react-native'
import { SafeAreaProvider, SafeAreaView } from 'react-native-safe-area-context'
import WebView, { type WebViewMessageEvent } from 'react-native-webview'

import { fetchReplayBlock, fetchReplaySources, MAX_PLAYER_BYTES, type ReplaySources } from '@/api/replayPlayback'
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

import { blockChunkScript, parsePlayerMessage, playerHtml } from './player/playerHtml'

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
    const bridge = useRef<{
        controller: AbortController
        inFlight: Set<number>
        bytes: number
        generation: number
    } | null>(null)

    useEffect(() => {
        const controller = new AbortController()
        bridge.current = { controller, inFlight: new Set(), bytes: 0, generation }
        setSources(null)
        setFailure(null)
        setLoading(true)
        if (!scope) return () => controller.abort()
        void fetchReplaySources(sessionId, controller.signal)
            .then((data) => {
                if (!controller.signal.aborted && generation === sessionGeneration()) setSources(data)
            })
            .catch((error: unknown) => {
                if (!controller.signal.aborted) {
                    reportScopeError(error, 'replay')
                    setFailure(actionErrorMessage(error))
                }
            })
        return () => controller.abort()
    }, [sessionId, scope, generation])

    useEffect(() => {
        const subscription = AppState.addEventListener('change', (state) => {
            if (state !== 'active') webview.current?.injectJavaScript('window.__pauseReplay?.();true;')
        })
        return () => subscription.remove()
    }, [])

    const fail = (message: string): void => {
        bridge.current?.controller.abort()
        setFailure(message)
    }
    useEffect(() => {
        if (!loading || failure) return
        const timer = setTimeout(() => {
            bridge.current?.controller.abort()
            setFailure('The player took too long to start. Try again.')
        }, 30_000)
        return () => clearTimeout(timer)
    }, [loading, failure])
    const onMessage = (event: WebViewMessageEvent): void => {
        if (!sources || !isPlayerUrl(event.nativeEvent.url)) return
        const message = parsePlayerMessage(event.nativeEvent.data, sources.sources.length)
        const current = bridge.current
        if (!message || !current || current.controller.signal.aborted || current.generation !== sessionGeneration())
            return
        if (message.type === 'ready') {
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
        if (current.inFlight.has(message.id)) return
        const source = sources.sources[message.index]
        if (!source) return
        current.inFlight.add(message.id)
        void fetchReplayBlock(sessionId, source, current.controller.signal)
            .then((text) => {
                if (current.controller.signal.aborted || current.generation !== sessionGeneration()) return
                current.bytes += text.length * 2
                if (current.bytes > MAX_PLAYER_BYTES) {
                    fail('This recording is too large to play on this device.')
                    return
                }
                for (let offset = 0; offset < text.length || offset === 0; offset += CHUNK_CHARACTERS) {
                    webview.current?.injectJavaScript(
                        blockChunkScript(
                            message.id,
                            text.slice(offset, offset + CHUNK_CHARACTERS),
                            offset + CHUNK_CHARACTERS >= text.length
                        )
                    )
                }
            })
            .catch((error: unknown) => {
                if (!current.controller.signal.aborted) {
                    reportScopeError(error, 'replay')
                    fail(actionErrorMessage(error))
                }
            })
            .finally(() => current.inFlight.delete(message.id))
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
                                setSupportMultipleWindows={false}
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
