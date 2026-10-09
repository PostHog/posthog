import { type ReactElement, type ReactNode, useRef } from 'react'
import { ScrollView, StyleSheet, Text, View } from 'react-native'

import { colors, radii, type } from '@/ui/tokens'

import { ChatErrorBubble } from './ChatErrorBubble'
import { ChatLinkCard } from './ChatLinkCard'
import { ChatMarkdown } from './ChatMarkdown'
import { ChatProgressLine } from './ChatProgressLine'
import type { ChatPhase } from './hooks'
import type { ChatEntry, ChatLinkTarget } from './types'

interface ThreadProps {
    messages: ChatEntry[]
    phase: ChatPhase
    onRetry: () => void
    linkUrl: (target: ChatLinkTarget) => string | undefined
}

function statusLine(messages: ChatEntry[], phase: ChatPhase): string | null {
    if (phase === 'idle') {
        return null
    }
    if (phase === 'reconnecting') {
        return 'Reconnecting…'
    }
    const last = messages[messages.length - 1]
    if (last?.kind === 'assistant' && last.progress) {
        return last.progress
    }
    if (last?.kind === 'assistant' && last.status === 'loading' && last.text) {
        return null
    }
    return 'Thinking…'
}

export function Thread({ messages, phase, onRetry, linkUrl }: ThreadProps): ReactElement {
    const scroll = useRef<ScrollView>(null)
    const status = statusLine(messages, phase)
    const lastIndex = messages.length - 1

    const renderEntry = (entry: ChatEntry, index: number): ReactNode => {
        switch (entry.kind) {
            case 'user':
                return (
                    <View key={entry.key} style={styles.userBubble}>
                        <Text style={styles.userText}>{entry.text}</Text>
                    </View>
                )
            case 'assistant':
                // A tool-call step has no text of its own; its progress shows in the status line.
                return entry.text ? (
                    <View key={entry.key} style={styles.assistant} testID="chat-assistant">
                        <ChatMarkdown text={entry.text} streaming={entry.status === 'loading'} />
                    </View>
                ) : null
            case 'failure':
                return (
                    <ChatErrorBubble
                        key={entry.key}
                        text={entry.text}
                        onRetry={index === lastIndex && phase === 'idle' ? onRetry : undefined}
                    />
                )
            case 'link':
                return <ChatLinkCard key={entry.key} text={entry.text} url={linkUrl(entry.target)} />
        }
    }

    return (
        <ScrollView
            ref={scroll}
            style={styles.scroll}
            contentContainerStyle={styles.content}
            onContentSizeChange={() => scroll.current?.scrollToEnd({ animated: true })}
            keyboardShouldPersistTaps="handled"
            keyboardDismissMode="interactive"
            testID="chat-thread"
        >
            {messages.map(renderEntry)}
            {status ? <ChatProgressLine text={status} /> : null}
        </ScrollView>
    )
}

const styles = StyleSheet.create({
    scroll: {
        flex: 1,
    },
    content: {
        paddingHorizontal: 20,
        paddingVertical: 12,
        gap: 14,
    },
    userBubble: {
        alignSelf: 'flex-end',
        maxWidth: '82%',
        backgroundColor: colors.sunken,
        borderRadius: radii.menuRow,
        paddingVertical: 10,
        paddingHorizontal: 14,
    },
    userText: {
        ...type.body,
        color: colors.ink,
    },
    assistant: {
        // Markdown blocks end with a 10pt bottom margin; this keeps the thread gap even.
        marginBottom: -10,
    },
})
