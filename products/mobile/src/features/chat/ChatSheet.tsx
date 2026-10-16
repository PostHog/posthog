import { type ReactElement, useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react'
import { Keyboard, StyleSheet, Text, type TextInput, useWindowDimensions, View } from 'react-native'
import { GestureDetector, GestureHandlerRootView } from 'react-native-gesture-handler'
import { useReanimatedKeyboardAnimation } from 'react-native-keyboard-controller'
import Animated, { useAnimatedStyle } from 'react-native-reanimated'

import { useProjectScope } from '@/auth/useProjectScope'
import { useDataMode } from '@/demo/demoMode'
import { track } from '@/lib/analytics'
import { isReportId } from '@/lib/ids'
import { useNow } from '@/lib/useNow'
import { reportWebUrl } from '@/model/adapters/report'
import type { InboxItem, ReportView } from '@/model/types'
import { CloseIcon } from '@/ui/icons/CloseIcon'
import { ComposeIcon } from '@/ui/icons/ComposeIcon'
import { OverlayHost } from '@/ui/OverlayPortal'
import { Pressable44 } from '@/ui/Pressable44'
import { Scrim } from '@/ui/Scrim'
import { colors, iconSizes, motion, radii, shadows, type } from '@/ui/tokens'
import { usePresence } from '@/ui/usePresence'
import { useScreenInsets } from '@/ui/useScreenInsets'
import { useSheetDrag } from '@/ui/useSheetDrag'

import { defaultModelSelection, isPermissionMode, modeLabel } from '../handoff/runOptions'
import { useModelCatalogue, useRunDefaults } from '../handoff/useRunOptions'
import { useInboxItems } from '../inbox/hooks'
import { AttachMenuSheet } from './attachments/AttachMenuSheet'
import { AttachmentChip } from './attachments/AttachmentChip'
import type { AttachmentSource, PendingAttachment } from './attachments/types'
import { releaseAttachments, useComposerAttachments } from './attachments/useComposerAttachments'
import { ChatAccessGate } from './ChatAccessGate'
import { ChatEmptyState } from './ChatEmptyState'
import { type ChatOptionsPage, ChatOptionsSheet } from './ChatOptionsSheet'
import { Composer } from './Composer'
import { ContextChip } from './ContextChip'
import {
    type ChatRunOptions,
    type ChatRunOptionsAction,
    chatPermissionMode,
    chatRunOptionsFromConfig,
    chatRunOptionsReducer,
    chipModelLabel,
    DEFAULT_CHAT_RUN_OPTIONS,
} from './chatRunOptions'
import { type ChatSheetSource, useChatSheetEvents } from './chatSheetEvents'
import { inboxContextItem, reportContextFromItem, reportContextFromView } from './contextPrompt'
import type { ChatDraft } from './draftStore'
import { MentionPopover } from './MentionPopover'
import {
    canDrain,
    EMPTY_QUEUE,
    joinQueue,
    joinQueueAttachments,
    type QueueState,
    queueActions,
    queueReducer,
    type SendGate,
    sendNowState,
    shouldQueue,
} from './messageQueue'
import { QueuedMessages } from './QueuedMessages'
import { SessionDecisionPanel } from './session/SessionDecisionPanel'
import { SessionThread } from './session/SessionThread'
import { type SessionOptions, useSession } from './session/useSession'
import type { ChatContext } from './types'
import { useChatDraft } from './useChatDraft'

/** The Discuss shape and the context block name each attached report, so the list stays short. */
const MAX_ATTACHED_REPORTS = 5

interface ChatSheetProps {
    initialReportId?: string
    initialTaskId?: string
    initialRunId?: string
    source: ChatSheetSource
    onClosed: () => void
}

function sessionTarget(taskId: string | undefined, runId: string | undefined): SessionOptions {
    if (!taskId) {
        return {}
    }
    return runId ? { taskId, runId } : { taskId }
}

export function ChatSheet({
    initialReportId,
    initialTaskId,
    initialRunId,
    source,
    onClosed,
}: ChatSheetProps): ReactElement {
    const insets = useScreenInsets()
    const { height: windowHeight } = useWindowDimensions()
    const now = useNow()
    const inbox = useInboxItems()
    const [target, setTarget] = useState<SessionOptions>(() => sessionTarget(initialTaskId, initialRunId))
    const session = useSession(target)
    const scope = useProjectScope()
    const demo = useDataMode() === 'demo'
    const keyboard = useReanimatedKeyboardAnimation()
    const preparingSend = useRef(false)
    const [preparing, setPreparing] = useState(false)
    const [visible, setVisible] = useState(true)
    const { progress } = usePresence(visible, motion.sheet)
    const close = useCallback((): void => setVisible(false), [])
    const { drag, pan } = useSheetDrag(visible, close)
    const [draftReportId, setDraftReportId] = useState(() =>
        initialReportId && isReportId(initialReportId, demo) ? initialReportId : undefined
    )
    const [draftTaskId, setDraftTaskId] = useState<string | null>(initialTaskId ?? null)
    const sheetEvents = useChatSheetEvents(
        { ...source, hasContext: draftReportId !== undefined, resumed: initialTaskId !== undefined },
        session.runId
    )
    useEffect(() => {
        if (!session.isSending && !session.unsentText && session.taskId) {
            setDraftTaskId(session.taskId)
        }
    }, [session.isSending, session.unsentText, session.taskId])
    const composerDraft = useChatDraft(draftTaskId, draftReportId, demo)
    const { text, reportIds: attached } = composerDraft.draft
    const setText = (value: string | ((current: string) => string)): void => {
        composerDraft.change({ ...composerDraft.draft, text: typeof value === 'function' ? value(text) : value })
    }
    const setAttached = (value: string[] | ((current: string[]) => string[])): void => {
        composerDraft.change({
            ...composerDraft.draft,
            reportIds: typeof value === 'function' ? value(attached) : value,
        })
    }
    const [queue, dispatchQueue] = useReducer(queueReducer, EMPTY_QUEUE)
    const delivering = useRef(false)
    const [isDelivering, setDelivering] = useState(false)
    // Bumped by New chat and by closing, so a delivery that settles afterwards leaves the new queue alone.
    const queueEpoch = useRef(0)
    const latest = useRef<{ queue: QueueState; draft: ChatDraft; change: (draft: ChatDraft) => void }>({
        queue,
        draft: composerDraft.draft,
        change: composerDraft.change,
    })
    useEffect(() => {
        latest.current = { queue, draft: composerDraft.draft, change: composerDraft.change }
    })
    const [reports, setReports] = useState<Record<string, ReportView>>({})
    const [mentionOpen, setMentionOpen] = useState(false)
    const mentionTrigger = useRef<'button' | 'typed'>('button')
    const [runOptions, dispatchRunOptions] = useReducer(chatRunOptionsReducer, DEFAULT_CHAT_RUN_OPTIONS)
    const pickedOptions = useRef(false)
    const [optionsOpen, setOptionsOpen] = useState(false)
    const [optionsPage, setOptionsPage] = useState<ChatOptionsPage>('model')
    const attachments = useComposerAttachments()
    const [attachOpen, setAttachOpen] = useState(false)
    // The files of the direct send in flight. They stay in the composer until it settles, and a queued message
    // never takes them.
    const [sendingFileIds, setSendingFileIds] = useState<readonly string[]>([])
    const input = useRef<TextInput>(null)
    const historyStatus = session.history.status
    const optionsDisabled =
        session.phase !== 'idle' || historyStatus !== 'idle' || session.isSending || session.decision !== undefined
    const runDefaults = useRunDefaults(true)
    const modelCatalogue = useModelCatalogue(
        true,
        runOptions.model === 'default' ? defaultModelSelection(runDefaults)?.model : runOptions.model.model
    )
    // A live run cannot switch harness, so an open chat stays on the harness its run uses.
    const runAdapter = session.taskId ? (session.runConfig?.runtimeAdapter ?? null) : null
    const permissionMode = chatPermissionMode(runOptions, runDefaults, runAdapter)

    const historyErrorKind = historyStatus === 'error' ? (session.history.error?.kind ?? 'unknown') : null
    useEffect(() => {
        if (historyErrorKind) {
            track('mobile_session_load_failed', { code: historyErrorKind })
        }
    }, [historyErrorKind])

    useEffect(() => {
        if (mentionOpen) {
            track('mobile_chat_mention_opened', { trigger: mentionTrigger.current })
        }
    }, [mentionOpen])

    useEffect(() => {
        if (optionsDisabled) {
            setOptionsOpen(false)
        }
    }, [optionsDisabled])

    useEffect(() => {
        if (visible) {
            return undefined
        }
        const timer = setTimeout(onClosed, motion.sheet)
        return () => clearTimeout(timer)
    }, [visible, onClosed])

    const hasRunConfig = session.runConfig !== undefined
    const seedAdapter = session.runConfig?.runtimeAdapter ?? null
    const seedModel = session.runConfig?.model ?? null
    const seedEffort = session.runConfig?.reasoningEffort ?? null
    const seedMode = session.runConfig?.permissionMode ?? null
    useEffect(() => {
        if (!hasRunConfig || pickedOptions.current) {
            return
        }
        dispatchRunOptions({
            type: 'seed',
            options: chatRunOptionsFromConfig({
                runtimeAdapter: seedAdapter,
                model: seedModel,
                reasoningEffort: seedEffort,
                permissionMode: seedMode,
            }),
        })
    }, [hasRunConfig, seedAdapter, seedModel, seedEffort, seedMode])

    // The agent can change mode on its own, such as out of Plan when a plan is approved. Its new mode replaces an
    // earlier pick, as the web drops its mode override on `current_mode_update`.
    useEffect(() => {
        if (pickedOptions.current && seedMode && isPermissionMode(seedMode)) {
            dispatchRunOptions({ type: 'mode', mode: seedMode })
        }
    }, [seedMode])

    const items = inbox.data ?? []
    const itemsById = useMemo(() => new Map(items.map((item) => [item.reportId, item])), [items])
    const mentionItems = useMemo(() => items.filter((item) => !attached.includes(item.reportId)), [items, attached])
    const canMention = attached.length < MAX_ATTACHED_REPORTS && mentionItems.length > 0
    const sheetStyle = useAnimatedStyle(() => ({
        transform: [{ translateY: (1 - progress.value) * windowHeight + drag.value }],
    }))
    // The sheet ends at the bottom edge of the window, so padding it by the keyboard height keeps the composer above
    // the keyboard. `height` is negative while the keyboard is open, and the keyboard covers the home indicator.
    const bottomInset = insets.bottom
    const keyboardStyle = useAnimatedStyle(() => ({ paddingBottom: Math.max(-keyboard.height.value, bottomInset) }))
    // A message sent before the stored history loads would land in a thread the person cannot see yet.
    const composerReady = composerDraft.ready && historyStatus === 'idle'
    const ready = composerReady && !preparing && !session.isSending
    const gate: SendGate = {
        phase: session.phase,
        sending: session.isSending || preparing || isDelivering,
        decisionPending: session.decision !== undefined,
    }
    const queueing = shouldQueue(gate, queue)
    // Queueing needs no network, so only a direct send waits for the previous one.
    const canSend = text.trim().length > 0 && (queueing ? composerReady : ready)
    const sendNow = sendNowState({
        ...gate,
        // A direct send only starts while the run is idle. Its promise can outlast the start, such as a demo reply
        // that resolves when the reply ends, and must not block steering the turn it started.
        sending: session.isSending || isDelivering || (preparing && session.phase === 'idle'),
        canSteer: session.canSteer,
        stopping: session.isStopping,
    })
    // Files stay in the composer until the send that uploads them settles. A demo send uploads nothing.
    const uploading = !demo && (preparing || session.isSending)
    const showEmptyState = session.taskId === null && session.items.length === 0 && historyStatus === 'idle'
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
        // The inbox list frames the first message of a new chat only. The agent has it in the thread after that.
        if (session.taskId === null && items.length > 0) {
            return { kind: 'inbox', items: items.map(inboxContextItem) }
        }
        return { kind: 'none' }
    }

    const changeText = (value: string): void => {
        setText(value)
        mentionTrigger.current = 'typed'
        setMentionOpen((open) => (value.endsWith('@') ? canMention : open && value.includes('@')))
    }
    const toggleMention = (): void => {
        mentionTrigger.current = 'button'
        setMentionOpen((open) => !open && canMention)
    }
    const openOptions = (page: ChatOptionsPage): void => {
        if (optionsDisabled) {
            return
        }
        // The keyboard would cover the sheet.
        Keyboard.dismiss()
        setMentionOpen(false)
        setOptionsPage(page)
        setOptionsOpen(true)
        track('mobile_chat_options_opened', { page })
    }
    const closeOptions = (): void => {
        setOptionsOpen(false)
        input.current?.focus()
    }
    const openAttach = (): void => {
        if (uploading) {
            return
        }
        // The keyboard would cover the sheet.
        Keyboard.dismiss()
        setMentionOpen(false)
        setAttachOpen(true)
        track('mobile_chat_attach_menu_opened')
    }
    const closeAttach = (): void => {
        setAttachOpen(false)
        input.current?.focus()
    }
    const pickAttachment = (source: AttachmentSource): void => {
        setAttachOpen(false)
        void attachments.pick(source).finally(() => input.current?.focus())
    }
    const notice = attachments.notice ?? session.notice
    const dismissNotice = (): void => {
        if (attachments.notice) {
            attachments.dismissNotice()
        } else {
            session.dismissNotice()
        }
    }
    const changeOptions = (action: ChatRunOptionsAction): void => {
        pickedOptions.current = true
        dispatchRunOptions(action)
    }
    const pickMention = (item: InboxItem): void => {
        if (!attached.includes(item.reportId)) {
            track('mobile_chat_report_attached', {
                attached_count: Math.min(attached.length + 1, MAX_ATTACHED_REPORTS),
            })
        }
        composerDraft.change({
            text: text.replace(/@$/, ''),
            reportIds: attached.includes(item.reportId)
                ? attached
                : [...attached, item.reportId].slice(0, MAX_ATTACHED_REPORTS),
        })
        setMentionOpen(false)
        input.current?.focus()
    }
    const detach = (reportId: string): void => {
        track('mobile_chat_report_removed', {
            attached_count: attached.filter((id) => id !== reportId).length,
            initial: reportId === initialReportId,
        })
        setAttached((previous) => previous.filter((id) => id !== reportId))
    }
    // Queued messages go back into the composer draft, so closing the sheet or starting a new chat loses none.
    // Returns the queued files; the draft cannot hold them.
    const foldQueue = (): PendingAttachment[] => {
        queueEpoch.current++
        const { queue: current, draft, change } = latest.current
        if (current.rows.length === 0) {
            return []
        }
        const next = { ...draft, text: [joinQueue(current.rows), draft.text.trim()].filter(Boolean).join('\n\n') }
        latest.current = { queue: EMPTY_QUEUE, draft: next, change }
        dispatchQueue(queueActions.clear())
        change(next)
        return joinQueueAttachments(current.rows)
    }
    // The draft keeps text only, so a closed sheet loses the queued files, as it loses unsent composer files.
    // biome-ignore lint/correctness/useExhaustiveDependencies: `foldQueue` reads only refs.
    useEffect(() => {
        if (!visible) {
            releaseAttachments(foldQueue())
        }
    }, [visible])
    // An Android back pops the route without the sheet's own close.
    // biome-ignore lint/correctness/useExhaustiveDependencies: `foldQueue` reads only refs.
    useEffect(() => () => releaseAttachments(foldQueue()), [])
    // The mode the chip shows, already mapped onto the harness the message runs on.
    const sendOptions = (): ChatRunOptions => ({ ...runOptions, permissionMode })
    const deliverQueue = (steer: boolean): void => {
        const rows = queue.rows
        if (rows.length === 0 || delivering.current) {
            return
        }
        const epoch = queueEpoch.current
        delivering.current = true
        setDelivering(true)
        // Cleared before the send, so a message queued while it is in flight waits for the next delivery.
        dispatchQueue(queueActions.clear())
        void session
            .send(joinQueue(rows), buildContext(), sendOptions(), {
                ...(steer ? { steer: true } : {}),
                queuedCount: rows.length,
                attachments: joinQueueAttachments(rows),
            })
            .catch(() => false)
            .then((sent) => {
                if (sent) {
                    sheetEvents.countSent()
                } else if (queueEpoch.current === epoch) {
                    // Held, because the failed send may have reached the agent, and a second automatic try could
                    // deliver it twice.
                    dispatchQueue(queueActions.restore(rows))
                }
            })
            .finally(() => {
                delivering.current = false
                setDelivering(false)
            })
    }
    const drainable = composerReady && canDrain(gate, queue)
    // biome-ignore lint/correctness/useExhaustiveDependencies: drains on the transition into a drainable state only.
    useEffect(() => {
        if (drainable) {
            deliverQueue(false)
        }
    }, [drainable])
    const sendQueueNow = (): void => {
        if (queue.rows.length === 0 || sendNow.pending || sendNow.disabledReason) {
            return
        }
        track('mobile_session_queue_sent_now', { queued_count: queue.rows.length, steer: session.canSteer })
        deliverQueue(true)
    }
    const removeQueued = (id: string): void => {
        releaseAttachments(queue.rows.find((row) => row.id === id)?.attachments ?? [])
        dispatchQueue(queueActions.remove(id))
        track('mobile_session_queue_removed', {
            queue_length: queue.rows.filter((row) => row.id !== id).length,
        })
    }
    const stop = (): void => {
        // The stopped turn ends like any other, so without the hold the queue would go out right after the Stop.
        dispatchQueue(queueActions.hold('cancelled'))
        session.stop()
    }
    const send = (): void => {
        const message = text.trim()
        if (!message || !composerReady) {
            return
        }
        if (queueing || preparingSend.current) {
            setMentionOpen(false)
            const queuedFiles = attachments.files.filter((file) => !sendingFileIds.includes(file.id))
            dispatchQueue(queueActions.enqueue(message, queuedFiles))
            attachments.clear({ only: queuedFiles.map((file) => file.id), release: false })
            track('mobile_session_queued', { queue_length: queue.rows.length + 1 })
            composerDraft.change({ text: '', reportIds: attached })
            return
        }
        if (!ready) {
            return
        }
        setMentionOpen(false)
        const options = sendOptions()
        const context = buildContext()
        const files = attachments.files
        attachments.dismissNotice()
        preparingSend.current = true
        setPreparing(true)
        setSendingFileIds(files.map((file) => file.id))
        if (demo) {
            // The bubble already shows the files, and a demo send settles only after the canned reply plays.
            attachments.clear({ only: files.map((file) => file.id), release: false })
        }
        void composerDraft
            .beginSend({ text: message, reportIds: attached })
            .then(async (settle) => {
                const sent = await session.send(message, context, options, { attachments: files }).catch(() => false)
                if (sent) {
                    sheetEvents.countSent()
                    attachments.clear({ only: files.map((file) => file.id), release: false })
                }
                await settle(sent)
            })
            .finally(() => {
                preparingSend.current = false
                setPreparing(false)
                setSendingFileIds([])
            })
    }
    const startNewChat = (): void => {
        sheetEvents.countNewChat()
        // The queued text folds into this chat's draft, so its files must not follow into the new chat.
        releaseAttachments(foldQueue())
        if (target.taskId) {
            // The session reloads as an empty new chat when its task option goes.
            setTarget({})
        } else {
            session.reset()
        }
        setDraftTaskId(null)
        setDraftReportId(undefined)
        setMentionOpen(false)
        setOptionsOpen(false)
        setAttachOpen(false)
        attachments.clear()
        pickedOptions.current = false
        dispatchRunOptions({ type: 'reset' })
        input.current?.focus()
    }

    const chips =
        attached.length > 0 || attachments.files.length > 0 ? (
            <>
                {attached.map((reportId) => (
                    <ContextChip
                        key={reportId}
                        reportId={reportId}
                        item={itemsById.get(reportId)}
                        onReport={rememberReport}
                        onRemove={() => detach(reportId)}
                    />
                ))}
                {attachments.files.map((file) => (
                    <AttachmentChip
                        key={file.id}
                        attachment={file}
                        uploading={uploading && sendingFileIds.includes(file.id)}
                        onRemove={() => attachments.remove(file.id)}
                    />
                ))}
            </>
        ) : null

    // The route is a native modal, so on Android the app's gesture root does not reach it and the sheet needs its own.
    return (
        <GestureHandlerRootView style={styles.overlay} testID="chat-sheet">
            <OverlayHost>
                <View style={styles.overlay}>
                    <Scrim color={colors.scrimChat} progress={progress} />
                    <Animated.View style={[styles.sheet, shadows.bottomSheet, sheetStyle]} accessibilityViewIsModal>
                        <Animated.View style={[styles.keyboard, keyboardStyle]}>
                            {/* The thread scrolls, so only the header takes the drag; a drag there never competes with a scroll. */}
                            <GestureDetector gesture={pan}>
                                <View style={styles.header} testID="chat-header">
                                    <View style={styles.grabber} />
                                    <View style={styles.headerRow}>
                                        <Pressable44
                                            onPress={close}
                                            accessibilityLabel="Close"
                                            pressedBackground={colors.background}
                                            style={styles.round}
                                            testID="chat-close"
                                        >
                                            <CloseIcon size={iconSizes.control} />
                                        </Pressable44>
                                        <Text style={styles.title} accessibilityRole="header" numberOfLines={1}>
                                            {session.title ?? 'New chat'}
                                        </Text>
                                        {showEmptyState ? (
                                            <View style={styles.headerSpacer} />
                                        ) : (
                                            <Pressable44
                                                onPress={startNewChat}
                                                accessibilityLabel="New chat"
                                                pressedBackground={colors.background}
                                                style={styles.round}
                                                testID="chat-new"
                                            >
                                                <ComposeIcon size={iconSizes.control} />
                                            </Pressable44>
                                        )}
                                    </View>
                                </View>
                            </GestureDetector>
                            {showEmptyState ? (
                                <ChatEmptyState
                                    reportCount={attached.length}
                                    suggestedPrompts={suggestedPrompts}
                                    onPrompt={setText}
                                />
                            ) : (
                                <SessionThread
                                    session={session}
                                    onRetryHistory={() => {
                                        track('mobile_session_load_retried')
                                        session.reloadHistory().catch(() => undefined)
                                    }}
                                />
                            )}
                            <View style={styles.composerArea}>
                                <ChatAccessGate onDecline={close}>
                                    <QueuedMessages
                                        rows={queue.rows}
                                        held={queue.hold !== null}
                                        onRemove={removeQueued}
                                        onSendNow={sendQueueNow}
                                        sendNowDisabledReason={sendNow.disabledReason}
                                        sendNowPending={sendNow.pending}
                                    />
                                    <SessionDecisionPanel
                                        decision={session.decision}
                                        notice={notice}
                                        pending={session.isSending}
                                        onAnswer={(answerInput) => void session.answer(answerInput)}
                                        onDismissNotice={dismissNotice}
                                    />
                                    {/* A pending decision has its own reply field, so it replaces the composer, as on the web. */}
                                    {session.decision ? null : (
                                        <>
                                            {mentionOpen ? (
                                                <MentionPopover items={mentionItems} now={now} onPick={pickMention} />
                                            ) : null}
                                            <Composer
                                                ref={input}
                                                text={text}
                                                onChangeText={changeText}
                                                chips={chips}
                                                onAttach={openAttach}
                                                attachOpen={attachOpen}
                                                attachDisabled={uploading}
                                                attachFull={attachments.isFull}
                                                mentionOpen={mentionOpen}
                                                onToggleMention={toggleMention}
                                                modelLabel={chipModelLabel(modelCatalogue.catalogue, runOptions.model)}
                                                modeLabel={modeLabel(permissionMode)}
                                                openOption={optionsOpen ? optionsPage : null}
                                                optionsDisabled={optionsDisabled}
                                                onOpenModel={() => openOptions('model')}
                                                onOpenMode={() => openOptions('mode')}
                                                onSend={send}
                                                canSend={canSend}
                                                isStreaming={session.phase !== 'idle'}
                                                onStop={stop}
                                            />
                                        </>
                                    )}
                                </ChatAccessGate>
                            </View>
                        </Animated.View>
                    </Animated.View>
                    <ChatOptionsSheet
                        visible={optionsOpen}
                        page={optionsPage}
                        catalogue={modelCatalogue}
                        defaults={runDefaults}
                        options={runOptions}
                        runAdapter={runAdapter}
                        onChange={changeOptions}
                        onClose={closeOptions}
                    />
                    <AttachMenuSheet visible={attachOpen} onPick={pickAttachment} onClose={closeAttach} />
                </View>
            </OverlayHost>
        </GestureHandlerRootView>
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
        paddingTop: 10,
    },
    grabber: {
        width: 40,
        height: 5,
        borderRadius: 3,
        backgroundColor: colors.border,
        alignSelf: 'center',
    },
    headerRow: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 12,
        paddingTop: 6,
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
        ...type.sheetTitle,
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
