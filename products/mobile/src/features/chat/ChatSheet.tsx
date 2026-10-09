import { type ReactElement, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { StyleSheet, Text, type TextInput, useWindowDimensions, View } from 'react-native'
import { useReanimatedKeyboardAnimation } from 'react-native-keyboard-controller'
import Animated, { useAnimatedStyle } from 'react-native-reanimated'

import { useProjectScope } from '@/auth/useProjectScope'
import { useDataMode } from '@/demo/demoMode'
import { isReportId } from '@/lib/ids'
import { useNow } from '@/lib/useNow'
import { reportWebUrl } from '@/model/adapters/report'
import type { InboxItem, ReportView } from '@/model/types'
import { CloseIcon } from '@/ui/icons/CloseIcon'
import { ComposeIcon } from '@/ui/icons/ComposeIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { Scrim } from '@/ui/Scrim'
import { colors, motion, radii, shadows, type } from '@/ui/tokens'
import { usePresence } from '@/ui/usePresence'
import { useScreenInsets } from '@/ui/useScreenInsets'

import { useInboxItems } from '../inbox/hooks'
import { ChatEmptyState } from './ChatEmptyState'
import { Composer } from './Composer'
import { ContextChip } from './ContextChip'
import { inboxContextItem, reportContextFromItem, reportContextFromView } from './contextPrompt'
import { useConversation } from './hooks'
import { MentionPopover } from './MentionPopover'
import { Thread } from './Thread'
import type { ChatContext, ChatLinkTarget } from './types'
import { chatLinkUrl } from './webLinks'

/** Each attached report adds up to its summary limit to every prompt, so the list stays short. */
const MAX_ATTACHED_REPORTS = 5

interface ChatSheetProps {
    initialReportId?: string
    onClosed: () => void
}

export function ChatSheet({ initialReportId, onClosed }: ChatSheetProps): ReactElement {
    const insets = useScreenInsets()
    const { height: windowHeight } = useWindowDimensions()
    const now = useNow()
    const inbox = useInboxItems()
    const conversation = useConversation()
    const scope = useProjectScope()
    const demo = useDataMode() === 'demo'
    const keyboard = useReanimatedKeyboardAnimation()
    const [visible, setVisible] = useState(true)
    const { progress } = usePresence(visible, motion.sheet)
    const [text, setText] = useState('')
    const [attached, setAttached] = useState<string[]>(() =>
        initialReportId && isReportId(initialReportId, demo) ? [initialReportId] : []
    )
    const [reports, setReports] = useState<Record<string, ReportView>>({})
    const [mentionOpen, setMentionOpen] = useState(false)
    const input = useRef<TextInput>(null)

    useEffect(() => {
        if (visible) {
            return undefined
        }
        const timer = setTimeout(onClosed, motion.sheet)
        return () => clearTimeout(timer)
    }, [visible, onClosed])

    const items = inbox.data ?? []
    const itemsById = useMemo(() => new Map(items.map((item) => [item.reportId, item])), [items])
    const mentionItems = useMemo(() => items.filter((item) => !attached.includes(item.reportId)), [items, attached])
    const canMention = attached.length < MAX_ATTACHED_REPORTS && mentionItems.length > 0
    const sheetStyle = useAnimatedStyle(() => ({ transform: [{ translateY: (1 - progress.value) * windowHeight }] }))
    // The sheet ends at the bottom edge of the window, so padding it by the keyboard height keeps the composer above
    // the keyboard. `height` is negative while the keyboard is open, and the keyboard covers the home indicator.
    const bottomInset = insets.bottom
    const keyboardStyle = useAnimatedStyle(() => ({ paddingBottom: Math.max(-keyboard.height.value, bottomInset) }))
    const canSend = text.trim().length > 0 && !conversation.isStreaming
    const webUrl = (reportId: string): string | undefined => (scope ? reportWebUrl(scope, reportId) : undefined)

    const rememberReport = useCallback((report: ReportView): void => {
        setReports((previous) => (previous[report.id] === report ? previous : { ...previous, [report.id]: report }))
    }, [])

    const onlyReport = attached.length === 1 ? reports[attached[0] as string] : undefined
    // The web shows a report's own prompts only when the agent may act on it.
    const suggestedPrompts = onlyReport?.canAct ? onlyReport.suggestedPrompts : undefined

    const buildContext = (): ChatContext => {
        if (attached.length > 0) {
            return {
                kind: 'reports',
                reports: attached.map((reportId) => {
                    const view = reports[reportId]
                    if (view) {
                        return reportContextFromView(view, webUrl(reportId))
                    }
                    const item = itemsById.get(reportId)
                    return item
                        ? reportContextFromItem(item, webUrl(reportId))
                        : { reportId, title: '', webUrl: webUrl(reportId), canAct: false }
                }),
            }
        }
        if (items.length > 0) {
            return { kind: 'inbox', items: items.map((item) => inboxContextItem(item, webUrl(item.reportId))) }
        }
        return { kind: 'none' }
    }

    const changeText = (value: string): void => {
        setText(value)
        setMentionOpen((open) => (value.endsWith('@') ? canMention : open && value.includes('@')))
    }
    const pickMention = (item: InboxItem): void => {
        setAttached((previous) =>
            previous.includes(item.reportId) ? previous : [...previous, item.reportId].slice(0, MAX_ATTACHED_REPORTS)
        )
        setMentionOpen(false)
        setText((value) => value.replace(/@$/, ''))
        input.current?.focus()
    }
    const detach = (reportId: string): void => {
        setAttached((previous) => previous.filter((id) => id !== reportId))
    }
    const send = (): void => {
        const message = text.trim()
        if (!message || conversation.isStreaming) {
            return
        }
        setText('')
        setMentionOpen(false)
        conversation.send(message, buildContext()).catch(() => undefined)
    }
    const startNewChat = (): void => {
        conversation.reset()
        setText('')
        setMentionOpen(false)
        input.current?.focus()
    }
    const linkUrl = (target: ChatLinkTarget): string | undefined => chatLinkUrl(target, conversation.conversationId)

    const chips =
        attached.length > 0
            ? attached.map((reportId) => (
                  <ContextChip
                      key={reportId}
                      reportId={reportId}
                      item={itemsById.get(reportId)}
                      onReport={rememberReport}
                      onRemove={() => detach(reportId)}
                  />
              ))
            : null

    return (
        <View style={styles.overlay} testID="chat-sheet">
            <Scrim color={colors.scrimChat} progress={progress} />
            <Animated.View style={[styles.sheet, shadows.bottomSheet, sheetStyle]} accessibilityViewIsModal>
                <Animated.View style={[styles.keyboard, keyboardStyle]}>
                    <View style={styles.header}>
                        <Pressable44
                            onPress={() => setVisible(false)}
                            accessibilityLabel="Close"
                            pressedBackground={colors.background}
                            style={styles.round}
                            testID="chat-close"
                        >
                            <CloseIcon size={16} />
                        </Pressable44>
                        <Text style={styles.title} accessibilityRole="header" numberOfLines={1}>
                            {conversation.title ?? 'New chat'}
                        </Text>
                        {conversation.messages.length > 0 ? (
                            <Pressable44
                                onPress={startNewChat}
                                accessibilityLabel="New chat"
                                pressedBackground={colors.background}
                                style={styles.round}
                                testID="chat-new"
                            >
                                <ComposeIcon size={18} />
                            </Pressable44>
                        ) : (
                            <View style={styles.headerSpacer} />
                        )}
                    </View>
                    {conversation.messages.length === 0 ? (
                        <ChatEmptyState
                            reportCount={attached.length}
                            suggestedPrompts={suggestedPrompts}
                            onPrompt={setText}
                        />
                    ) : (
                        <Thread
                            messages={conversation.messages}
                            phase={conversation.phase}
                            onRetry={() => {
                                conversation.retry().catch(() => undefined)
                            }}
                            linkUrl={linkUrl}
                        />
                    )}
                    <View style={styles.composerArea}>
                        {mentionOpen ? <MentionPopover items={mentionItems} now={now} onPick={pickMention} /> : null}
                        <Composer
                            ref={input}
                            text={text}
                            onChangeText={changeText}
                            chips={chips}
                            mentionOpen={mentionOpen}
                            onToggleMention={() => setMentionOpen((open) => !open && canMention)}
                            onSend={send}
                            canSend={canSend}
                            isStreaming={conversation.isStreaming}
                            onStop={conversation.stop}
                        />
                    </View>
                </Animated.View>
            </Animated.View>
        </View>
    )
}

const styles = StyleSheet.create({
    overlay: {
        flex: 1,
        justifyContent: 'flex-end',
    },
    sheet: {
        height: '94%',
        backgroundColor: colors.white,
        borderTopLeftRadius: radii.floating,
        borderTopRightRadius: radii.floating,
    },
    keyboard: {
        flex: 1,
    },
    header: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 12,
        paddingTop: 18,
        paddingHorizontal: 16,
        paddingBottom: 8,
    },
    round: {
        width: 44,
        height: 44,
        borderRadius: 22,
        borderWidth: 1,
        borderColor: colors.hairline,
        backgroundColor: colors.white,
        alignItems: 'center',
        justifyContent: 'center',
    },
    title: {
        ...type.sectionHeader,
        color: colors.ink,
        flexShrink: 1,
        textAlign: 'center',
    },
    headerSpacer: {
        width: 44,
        height: 44,
    },
    composerArea: {
        position: 'relative',
    },
})
