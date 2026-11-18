import * as Crypto from 'expo-crypto'
import { type ComponentType, type ReactElement, type Ref, useEffect, useMemo, useRef, useState } from 'react'
import { type StyleProp, StyleSheet, View, type ViewStyle } from 'react-native'
import WebView, { type WebViewMessageEvent, type WebViewProps } from 'react-native-webview'

import { PLAYER_ORIGIN, playerHtml } from './playerHtml'
import type { PageHandle, WebReplayPlayer } from './WebReplayPlayer'

interface InjectableWebView {
    injectJavaScript: (script: string) => void
}

// The class's own JSX typing rejects a ref under React 19's types, so the element is typed by the props it takes.
const PlayerWebView = WebView as unknown as ComponentType<WebViewProps & { ref?: Ref<InjectableWebView> }>

function isPlayerUrl(url: string): boolean {
    return url === PLAYER_ORIGIN || url === PLAYER_ORIGIN.slice(0, -1) || url.startsWith('about:')
}

interface ReplayWebViewProps {
    player: WebReplayPlayer
    style?: StyleProp<ViewStyle>
}

/** The page that replays one recording. It takes no touches: the card above it owns every gesture. */
export function ReplayWebView({ player, style }: ReplayWebViewProps): ReactElement {
    const ref = useRef<InjectableWebView | null>(null)
    const [pageVersion, setPageVersion] = useState(0)
    const currentVersion = useRef(0)
    const restart = (): void => {
        if (pageVersion === currentVersion.current) {
            currentVersion.current += 1
            player.restart()
            setPageVersion(currentVersion.current)
        }
    }
    const html = useMemo(() => playerHtml(Crypto.randomUUID()), [])
    useEffect(() => {
        const page: PageHandle = { inject: (script) => ref.current?.injectJavaScript(script) }
        player.attach(page)
        return () => player.detach(page)
    }, [player])

    const onMessage = (event: WebViewMessageEvent): void => {
        if (pageVersion === currentVersion.current && isPlayerUrl(event.nativeEvent.url)) {
            player.onPageMessage(event.nativeEvent.data)
        }
    }

    return (
        <View style={[styles.page, style]} pointerEvents="none">
            <PlayerWebView
                key={pageVersion}
                ref={ref}
                source={{ html, baseUrl: PLAYER_ORIGIN }}
                originWhitelist={['*']}
                onShouldStartLoadWithRequest={(request: { url: string }): boolean => isPlayerUrl(request.url)}
                onMessage={onMessage}
                onContentProcessDidTerminate={restart}
                onRenderProcessGone={restart}
                onOpenWindow={(): void => undefined}
                setSupportMultipleWindows
                javaScriptCanOpenWindowsAutomatically={false}
                allowFileAccess={false}
                allowFileAccessFromFileURLs={false}
                allowUniversalAccessFromFileURLs={false}
                mixedContentMode="never"
                sharedCookiesEnabled={false}
                thirdPartyCookiesEnabled={false}
                incognito
                javaScriptEnabled
                mediaPlaybackRequiresUserAction
                scrollEnabled={false}
                bounces={false}
                style={styles.page}
            />
        </View>
    )
}

const styles = StyleSheet.create({
    page: { flex: 1, backgroundColor: 'transparent' },
})
