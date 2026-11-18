import { type ReactNode, useEffect, useMemo, useState } from 'react'
import { ActivityIndicator, Platform, ScrollView, View } from 'react-native'
import WebView from 'react-native-webview'
import { track } from '@/lib/analytics'
import {
    type DiagramSize,
    hasRemoteImageNode,
    inlineScriptSource,
    mermaidHtml,
    parseMermaidMessage,
    rememberSize,
} from '@/lib/mermaid'
import { createStyles, useColorSchemeName, useColors } from '@/ui/theme'

const PADDING = 12
const PENDING_HEIGHT = 120
const SIZE_CACHE_LIMIT = 50

let bundle: string | null = null

// Metro exports the prebuilt browser bundle as a string (see metro.transformer.js).
function mermaidBundle(): string {
    bundle ??= inlineScriptSource(require('mermaid/dist/mermaid.min.js') as string)
    return bundle
}

// Remounted rows keep their height instead of jumping while the WebView loads.
const sizes = new Map<string, DiagramSize>()

type DiagramFailure = 'timeout' | 'render_error' | 'load_error' | 'process_gone' | 'open_window'

// A remounted row fails again for the same diagram, so each diagram reports its failure once.
const reportedFailures = new Set<string>()

function reportFailure(cacheKey: string, reason: DiagramFailure): void {
    if (reportedFailures.has(cacheKey)) return
    if (reportedFailures.size >= SIZE_CACHE_LIMIT) reportedFailures.clear()
    reportedFailures.add(cacheKey)
    track('mobile_chat_diagram_failed', { reason })
}

interface MermaidDiagramProps {
    code: string
    fallback: ReactNode
}

// Keyed by theme and code, so a new diagram starts without the old failure or size.
export function MermaidDiagram(props: MermaidDiagramProps): ReactNode {
    const dark = useColorSchemeName() === 'dark'
    const key = `${dark ? 'dark' : 'light'}\n${props.code}`
    if (Platform.OS === 'web' || hasRemoteImageNode(props.code)) return props.fallback
    return <DiagramView key={key} cacheKey={key} dark={dark} {...props} />
}

interface DiagramViewProps extends MermaidDiagramProps {
    cacheKey: string
    dark: boolean
}

function DiagramView({ code, fallback, cacheKey, dark }: DiagramViewProps): ReactNode {
    const colors = useColors()
    const styles = useStyles()
    const html = useMemo(() => mermaidHtml(code, dark, mermaidBundle()), [code, dark])
    const [width, setWidth] = useState(0)
    const [size, setSize] = useState(() => sizes.get(cacheKey) ?? null)
    const [failed, setFailed] = useState(false)

    useEffect(() => {
        if (size || failed) return
        const timeout = setTimeout(() => {
            reportFailure(cacheKey, 'timeout')
            setFailed(true)
        }, 15000)
        return () => clearTimeout(timeout)
    }, [size, failed, cacheKey])

    if (failed) return fallback

    const fail = (reason: DiagramFailure) => {
        reportFailure(cacheKey, reason)
        setFailed(true)
    }
    const onMessage = (data: string) => {
        const message = parseMermaidMessage(data)
        if (message?.type === 'size') {
            const next = { width: message.width, height: message.height }
            rememberSize(sizes, cacheKey, next, SIZE_CACHE_LIMIT)
            setSize(next)
        } else if (message?.type === 'error') {
            fail('render_error')
        }
    }

    return (
        <View style={styles.frame} onLayout={(event) => setWidth(event.nativeEvent.layout.width - PADDING * 2)}>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.content}>
                {width > 0 ? (
                    <WebView
                        source={{ html }}
                        originWhitelist={['*']}
                        onShouldStartLoadWithRequest={(request) => request.url === 'about:blank'}
                        onMessage={(event) => onMessage(event.nativeEvent.data)}
                        onError={() => fail('load_error')}
                        onContentProcessDidTerminate={() => fail('process_gone')}
                        onRenderProcessGone={() => fail('process_gone')}
                        onOpenWindow={() => fail('open_window')}
                        allowFileAccess={false}
                        allowFileAccessFromFileURLs={false}
                        allowUniversalAccessFromFileURLs={false}
                        mixedContentMode="never"
                        javaScriptCanOpenWindowsAutomatically={false}
                        javaScriptEnabled
                        scrollEnabled={false}
                        bounces={false}
                        setSupportMultipleWindows={false}
                        showsHorizontalScrollIndicator={false}
                        showsVerticalScrollIndicator={false}
                        style={[styles.webview, size ?? { width, height: PENDING_HEIGHT, opacity: 0 }]}
                    />
                ) : (
                    <View style={{ height: PENDING_HEIGHT }} />
                )}
            </ScrollView>
            {size ? null : (
                <View pointerEvents="none" style={styles.spinner}>
                    <ActivityIndicator color={colors.secondary} />
                </View>
            )}
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    frame: {
        backgroundColor: colors.background,
        borderRadius: 12,
        overflow: 'hidden',
    },
    content: {
        flexGrow: 1,
        justifyContent: 'center',
        padding: PADDING,
    },
    webview: { backgroundColor: 'transparent' },
    spinner: {
        position: 'absolute',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        alignItems: 'center',
        justifyContent: 'center',
    },
}))
