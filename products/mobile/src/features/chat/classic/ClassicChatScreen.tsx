import { BlurTargetView } from 'expo-blur'
import { type ReactElement, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
    ActivityIndicator,
    Keyboard,
    ScrollView,
    Text,
    type TextInputInstance,
    View,
    type ViewInstance,
} from 'react-native'
import { useReanimatedKeyboardAnimation } from 'react-native-keyboard-controller'
import Animated, { useAnimatedStyle } from 'react-native-reanimated'

import type { getConversation } from '@/api/conversations'
import { useProjectScope } from '@/auth/useProjectScope'
import { track } from '@/lib/analytics'
import { conversationWebUrl } from '@/model/adapters/chats'
import { READING_WIDTH } from '@/ui/adaptiveLayout'
import { OverlayHost } from '@/ui/OverlayPortal'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'
import { useScreenInsets } from '@/ui/useScreenInsets'

import { ChatAccessGate } from '../ChatAccessGate'
import { ChatEmptyState } from '../ChatEmptyState'
import { ChatErrorNotice } from '../ChatErrorNotice'
import { CHAT_HEADER_HEIGHT, ChatHeader } from '../ChatHeader'
import { type ChatSheetSource, useChatSheetEvents } from '../chatSheetEvents'
import { SessionThread, type SessionThreadState } from '../session/SessionThread'
import { useChatDraft } from '../useChatDraft'
import { ClassicComposer } from './ClassicComposer'
import { classicThreadItems } from './classicMessages'
import { useClassicChat } from './useClassicChat'

interface ClassicChatScreenProps {
    conversationId?: string
    initialConversation?: Awaited<ReturnType<typeof getConversation>>
    source: ChatSheetSource
    autoFocus: boolean
    onBack: () => void
    onNewChat: () => void
}

export function ClassicChatScreen({
    conversationId,
    initialConversation,
    source,
    autoFocus,
    onBack,
    onNewChat,
}: ClassicChatScreenProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const chat = useClassicChat(conversationId, initialConversation)
    const events = useChatSheetEvents(
        { ...source, conversationId: chat.id, runtime: 'langgraph', hasContext: false, resumed: !!conversationId },
        null
    )
    const scope = useProjectScope()
    const insets = useScreenInsets()
    const blurTarget = useRef<ViewInstance>(null)
    const input = useRef<TextInputInstance>(null)
    const draft = useChatDraft(chat.id, undefined, false, 'conversation')
    const [sending, setSending] = useState(false)
    const [saving, setSaving] = useState(false)
    const saveLock = useRef(false)
    const sendLock = useRef(false)
    const lifetime = useRef(0)
    useEffect(
        () => () => {
            lifetime.current++
        },
        []
    )
    const keyboard = useReanimatedKeyboardAnimation()
    const keyboardStyle = useAnimatedStyle(() => ({ paddingBottom: Math.max(-keyboard.height.value, insets.bottom) }))
    const projectUrl = scope ? `${scope.host.replace(/\/$/, '')}/project/${scope.projectId}` : ''
    const items = useMemo(() => classicThreadItems(chat.state, projectUrl), [chat.state, projectUrl])
    const thread: SessionThreadState = {
        history: {
            status: items.length > 0 ? 'idle' : chat.loading ? 'loading' : chat.historyError ? 'error' : 'idle',
            error: chat.historyError ? { kind: 'unknown', message: chat.historyError } : null,
        },
        items,
        invocations: new Map(),
        phase: chat.working ? 'working' : 'idle',
        stage: chat.state.progress ?? undefined,
        runStatus: null,
    }
    const send = async (): Promise<void> => {
        const text = draft.draft.text.trim()
        if (!text || sendLock.current || chat.working || chat.loading || !draft.ready) return
        sendLock.current = true
        setSending(true)
        const generation = lifetime.current
        try {
            const settle = await draft.beginSend({ text, reportIds: [] })
            if (generation !== lifetime.current) {
                await settle(false)
                return
            }
            let settled = false
            const accepted = await chat.send(text, async () => {
                await settle(true)
                settled = true
            })
            if (!settled) await settle(accepted)
            if (accepted) {
                events.countSent()
                track('mobile_session_sent', { agent_runtime: 'langgraph', conversation_id: chat.id })
            }
        } finally {
            sendLock.current = false
            if (generation === lifetime.current) setSending(false)
        }
    }
    const retrySave = async (): Promise<void> => {
        if (saveLock.current) return
        saveLock.current = true
        setSaving(true)
        try {
            await draft.retrySave()
        } finally {
            saveLock.current = false
            setSaving(false)
        }
    }
    const close = (): void => {
        lifetime.current++
        Keyboard.dismiss()
        onBack()
    }
    const approval = chat.state.approval
    const inputRef = useCallback(
        (node: TextInputInstance | null): void => {
            input.current = node
            if (autoFocus) node?.focus()
        },
        [autoFocus]
    )
    return (
        <View style={styles.screen} testID="classic-chat-screen">
            <OverlayHost>
                <BlurTargetView ref={blurTarget} style={styles.content}>
                    <Animated.View style={[styles.fill, keyboardStyle]}>
                        {!chat.loading && !chat.historyError && items.length === 0 ? (
                            <ScrollView
                                style={styles.fill}
                                contentContainerStyle={{
                                    flexGrow: 1,
                                    paddingTop: insets.top + CHAT_HEADER_HEIGHT,
                                    paddingBottom: 16,
                                }}
                                keyboardShouldPersistTaps="handled"
                                keyboardDismissMode="on-drag"
                            >
                                <ChatEmptyState
                                    reportCount={0}
                                    description="Ask about your product and explore your data."
                                    suggestedPrompts={[
                                        'Summarize this week',
                                        'What are my top events?',
                                        'Where are users dropping off?',
                                    ]}
                                    onPrompt={(text) => draft.change({ text, reportIds: [] })}
                                />
                            </ScrollView>
                        ) : (
                            <SessionThread
                                feedbackContext={chat.id ? { sessionId: chat.id, runtime: 'langgraph' } : undefined}
                                session={thread}
                                onRetryHistory={() => void chat.reload()}
                                topInset={insets.top + CHAT_HEADER_HEIGHT}
                            />
                        )}
                        {items.length > 0 && chat.historyError ? (
                            <View style={styles.recovery}>
                                <ChatErrorNotice
                                    message={chat.historyError}
                                    actions={
                                        <Pressable44
                                            disabled={chat.loading || chat.working}
                                            accessibilityRole="button"
                                            accessibilityLabel="Reconnect"
                                            onPress={() => void chat.reload()}
                                            style={styles.action}
                                        >
                                            {chat.loading ? <ActivityIndicator color={colors.ink} /> : null}
                                            <Text style={styles.label}>Reconnect</Text>
                                        </Pressable44>
                                    }
                                />
                            </View>
                        ) : null}
                        <ChatAccessGate onDecline={close}>
                            {draft.draftError ? (
                                <ChatErrorNotice
                                    message={draft.draftError}
                                    actions={
                                        <Pressable44
                                            disabled={saving}
                                            accessibilityRole="button"
                                            accessibilityLabel="Retry saving draft"
                                            onPress={() => void retrySave()}
                                            style={styles.action}
                                        >
                                            {saving ? <ActivityIndicator color={colors.ink} /> : null}
                                            <Text style={styles.label}>Retry saving draft</Text>
                                        </Pressable44>
                                    }
                                />
                            ) : null}
                            {chat.error ? <ChatErrorNotice message={chat.error} onDismiss={chat.dismissError} /> : null}
                            {approval ? (
                                <View style={styles.approval} testID="classic-approval">
                                    <Text style={styles.label}>{approval.toolName}</Text>
                                    <Text style={styles.body}>{approval.preview}</Text>
                                    <View style={styles.actions}>
                                        {chat.working ? <ActivityIndicator color={colors.ink} /> : null}
                                        <Pressable44
                                            disabled={chat.working}
                                            accessibilityRole="button"
                                            accessibilityLabel="Reject change"
                                            onPress={() => void chat.answer(false)}
                                            style={styles.action}
                                        >
                                            <Text style={styles.label}>Reject</Text>
                                        </Pressable44>
                                        <Pressable44
                                            disabled={chat.working}
                                            accessibilityRole="button"
                                            accessibilityLabel="Approve change"
                                            onPress={() => void chat.answer(true)}
                                            style={styles.action}
                                        >
                                            <Text style={styles.label}>Approve</Text>
                                        </Pressable44>
                                    </View>
                                </View>
                            ) : (
                                <ClassicComposer
                                    ref={inputRef}
                                    text={draft.draft.text}
                                    onChangeText={(text) => draft.change({ ...draft.draft, text })}
                                    onSend={() => void send()}
                                    onStop={() => void chat.stop()}
                                    disabled={!draft.ready || chat.loading || !!chat.historyError || sending}
                                    working={chat.working}
                                    stopping={chat.stopping}
                                />
                            )}
                        </ChatAccessGate>
                    </Animated.View>
                </BlurTargetView>
                <ChatHeader
                    blurTarget={blurTarget}
                    webUrl={conversationWebUrl(scope, chat.id)}
                    onBack={close}
                    onNewChat={() => {
                        lifetime.current++
                        events.countNewChat()
                        chat.reset()
                        onNewChat()
                    }}
                />
            </OverlayHost>
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    screen: { flex: 1, backgroundColor: colors.surface },
    fill: { flex: 1 },
    content: { flex: 1, width: '100%', maxWidth: READING_WIDTH, alignSelf: 'center' },
    recovery: { margin: 10 },
    approval: {
        margin: 10,
        padding: 12,
        borderWidth: 1,
        borderColor: colors.hairline,
        borderRadius: radii.card,
        gap: 8,
    },
    label: { ...type.bodyStrong, color: colors.ink },
    body: { ...type.body, color: colors.ink },
    actions: { flexDirection: 'row', justifyContent: 'flex-end', gap: 8 },
    action: { paddingHorizontal: 12, backgroundColor: colors.sunken, borderRadius: radii.pill },
}))
