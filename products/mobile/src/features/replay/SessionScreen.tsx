import * as Clipboard from 'expo-clipboard'
import { useRouter } from 'expo-router'
import { type ReactElement, useEffect, useRef, useState } from 'react'
import { Linking, Platform, ScrollView, Share, Text, View } from 'react-native'
import { useViewer } from '@/auth/useViewer'
import { RECORDING_OBJECT_TYPE } from '@/features/chat/objectContext'
import { HeaderMenu } from '@/features/views/screen/HeaderMenu'
import { useViewBack } from '@/features/views/screen/ViewScreenFrame'
import { ViewsReauthState } from '@/features/views/ViewsReauthState'
import { useToasts, ViewsToast } from '@/features/views/ViewsToast'
import { formatClock, formatMonthDay } from '@/lib/dates'
import { safeHttpsUrl } from '@/lib/urls'
import type { QueryState } from '@/model/types'
import { ComposeIcon } from '@/ui/icons/ComposeIcon'
import { CopyIcon } from '@/ui/icons/CopyIcon'
import { ExternalLinkIcon } from '@/ui/icons/ExternalLinkIcon'
import { FlagIcon } from '@/ui/icons/FlagIcon'
import { GlobeIcon } from '@/ui/icons/GlobeIcon'
import { RecordingIcon } from '@/ui/icons/RecordingIcon'
import { WarningIcon } from '@/ui/icons/WarningIcon'
import { OverlayHost } from '@/ui/OverlayPortal'
import { Pressable44 } from '@/ui/Pressable44'
import { StateView } from '@/ui/StateView'
import { SCREEN_CONTENT_TOP } from '@/ui/screenLayout'
import { createStyles, useColors, useTheme } from '@/ui/theme'
import { iconSizes, layout, prettyWrap, radii, type } from '@/ui/tokens'
import { bottomOffset, topOffset, useScreenInsets } from '@/ui/useScreenInsets'
import { type ScrollTitleState, useScrollTitle } from '@/ui/useScrollTitle'

import { ChapterList } from './ChapterList'
import { FrameSheet } from './FrameSheet'
import {
    isNotFound,
    type SessionSummaryFlow,
    useOrgAiStatus,
    useRecording,
    useReplayContext,
    useSessionSummaryFlow,
    useSessionTimeline,
} from './hooks'
import {
    trackChapterOpened,
    trackFullReplayOpened,
    trackReplayErrorShown,
    trackSessionChatOpened,
    trackSessionIdCopied,
    trackSessionIssueOpened,
    trackSessionOpened,
    trackSessionShared,
} from './replayAnalytics'
import { type SessionOpenSource, sessionWebUrl, shareSeconds } from './replayLinks'
import type { RecordingView, SessionTimeline } from './replayModel'
import { SessionChrome } from './SessionChrome'
import { SessionSkeleton } from './SessionSkeleton'
import { SessionTimelineSection } from './SessionTimelineSection'
import { SummaryCard } from './SummaryCard'
import { fallbackTitle, formatDuration, formatOffset } from './sessionAdapters'

interface SessionScreenProps {
    sessionId: string
    /** Seconds into the recording that the link pointed at. */
    t?: number
    source?: SessionOpenSource
}

export function SessionScreen({ sessionId, t, source = 'other' }: SessionScreenProps): ReactElement {
    return (
        <OverlayHost>
            <SessionContent sessionId={sessionId} t={t} source={source} />
        </OverlayHost>
    )
}

function SessionContent({
    sessionId,
    t,
    source,
}: Required<Omit<SessionScreenProps, 't'>> & { t?: number }): ReactElement {
    const styles = useStyles()
    const colors = useColors()
    const back = useViewBack()
    const { mode, access, ready } = useReplayContext()
    const recording = useRecording(sessionId)

    if (mode === 'demo') {
        return (
            <Frame onBack={back}>
                <StateView
                    icon={<RecordingIcon size={iconSizes.empty} color={colors.tertiary} />}
                    title="Sessions aren't in the demo"
                    message="Sign in to your PostHog project to see its recordings."
                    testID="session-demo"
                />
            </Frame>
        )
    }
    if (mode === 'live' && access.state !== 'ok') {
        return (
            <Frame onBack={back}>
                <ViewsReauthState access={access} feature="replay" />
            </Frame>
        )
    }
    if (recording.isError) {
        const notFound = isNotFound(recording.error)
        return (
            <Frame onBack={back}>
                <ErrorState
                    kind={notFound ? 'not_found' : 'recording'}
                    title={notFound ? "Couldn't find this recording" : "Couldn't load this session"}
                    message={
                        notFound
                            ? 'It may have expired or been deleted. Go back and pick another session.'
                            : 'Check your connection and try again.'
                    }
                    actionLabel={notFound ? 'Go back' : 'Try again'}
                    onAction={notFound ? back : () => void recording.refetch()}
                />
            </Frame>
        )
    }
    if (!ready || !recording.data) {
        return (
            <Frame onBack={back}>
                <View style={[styles.content, { paddingTop: 0 }]}>
                    <SessionSkeleton />
                </View>
            </Frame>
        )
    }
    return <SessionBody recording={recording.data} t={t} source={source} onBack={back} />
}

function Frame({ onBack, children }: { onBack: () => void; children: ReactElement }): ReactElement {
    const styles = useStyles()
    const insets = useScreenInsets()
    return (
        <View style={styles.screen}>
            <View style={[styles.fill, { paddingTop: topOffset(insets, SCREEN_CONTENT_TOP) }]}>{children}</View>
            <SessionChrome onBack={onBack} />
        </View>
    )
}

function ErrorState(props: {
    kind: 'not_found' | 'recording'
    title: string
    message: string
    actionLabel: string
    onAction: () => void
}): ReactElement {
    const colors = useColors()
    const { kind } = props
    useEffect(() => {
        trackReplayErrorShown(kind)
    }, [kind])
    return (
        <StateView
            icon={<WarningIcon size={iconSizes.empty} color={colors.tertiary} />}
            title={props.title}
            message={props.message}
            actionLabel={props.actionLabel}
            onAction={props.onAction}
            testID={`session-error-${kind}`}
        />
    )
}

interface SessionBodyProps {
    recording: RecordingView
    t?: number
    source: SessionOpenSource
    onBack: () => void
}

function SessionBody({ recording, t, source, onBack }: SessionBodyProps): ReactElement {
    const styles = useStyles()
    const { colors, shadows } = useTheme()
    const insets = useScreenInsets()
    const router = useRouter()
    const { scope } = useReplayContext()
    const { projectName } = useViewer()
    const aiStatus = useOrgAiStatus()
    const timeline = useSessionTimeline(recording)
    const flow = useSessionSummaryFlow(recording.sessionId)
    const toasts = useToasts()
    const [menuOpen, setMenuOpen] = useState(false)
    const [framePosition, setFramePosition] = useState<number | null>(null)
    const { sessionId } = recording
    const summary = flow.summary
    const scrollTitle = useScrollTitle(summary?.title ?? fallbackTitle(recording, timeline.data ?? null))
    const seconds = shareSeconds(summary?.keyMomentMs ?? null, t)
    const webUrl = sessionWebUrl(scope, sessionId, seconds)
    const safeWebUrl = webUrl ? safeHttpsUrl(webUrl) : undefined

    useOpenedEvent(sessionId, source, flow)

    const openFull = (): void => {
        if (!safeWebUrl) {
            return
        }
        trackFullReplayOpened(sessionId)
        Linking.openURL(safeWebUrl).catch(() => undefined)
    }
    const share = (): void => {
        if (!safeWebUrl) {
            return
        }
        trackSessionShared(sessionId, seconds)
        const title = `${recording.personLabel} at ${formatOffset(seconds * 1000)}`
        // iOS shows the URL as a link preview; Android shares text, so the URL goes in the message there.
        const content = Platform.OS === 'ios' ? { url: safeWebUrl, title } : { message: safeWebUrl, title }
        Share.share(content).catch(() => undefined)
    }
    const copyId = (): void => {
        trackSessionIdCopied(sessionId)
        Clipboard.setStringAsync(sessionId)
            .then(() => toasts.show('Copied'))
            .catch(() => toasts.show("Couldn't copy the session ID"))
    }
    const openChat = (): void => {
        trackSessionChatOpened(sessionId)
        const date = recording.startedAt ? ` · ${formatMonthDay(new Date(recording.startedAt))}` : ''
        router.push({
            pathname: '/chat',
            params: {
                entry: 'replay',
                objectType: RECORDING_OBJECT_TYPE,
                objectId: sessionId,
                objectLabel: `${recording.personLabel}${date}`,
            },
        })
    }
    const openIssue = (issueId: string): void => {
        trackSessionIssueOpened(sessionId)
        router.push({ pathname: '/errors/[id]', params: { id: issueId, from: 'replay' } })
    }
    const chapters = summary?.chapters ?? []
    const openChapter = (position: number): void => {
        const chapter = chapters[position]
        if (chapter) {
            trackChapterOpened({ sessionId, index: chapter.index, isKeyMoment: chapter.isKeyMoment })
            setFramePosition(position)
        }
    }
    const keyChapter = chapters.findIndex((chapter) => chapter.isKeyMoment)

    return (
        <View style={styles.screen}>
            <ScrollView
                style={styles.fill}
                contentContainerStyle={[
                    styles.content,
                    {
                        paddingTop: topOffset(insets, SCREEN_CONTENT_TOP),
                        paddingBottom: bottomOffset(insets, 120),
                    },
                ]}
                onScroll={scrollTitle.onScroll}
                scrollEventThrottle={16}
                testID="session-scroll"
            >
                <Header
                    onTitleLayout={scrollTitle.onTitleLayout}
                    recording={recording}
                    timeline={timeline}
                    projectName={projectName}
                    title={summary?.title ?? null}
                    keyMomentMs={summary?.keyMomentMs ?? null}
                    onKeyMoment={keyChapter >= 0 ? () => openChapter(keyChapter) : null}
                />
                <SummaryCard
                    card={flow.card}
                    aiStatus={aiStatus}
                    pending={flow.pending}
                    onSummarize={flow.summarize}
                    onCheckAgain={flow.checkAgain}
                />
                {summary ? (
                    <ChapterList
                        observationId={summary.observationId}
                        chapters={chapters}
                        onOpen={(chapter) => openChapter(chapters.indexOf(chapter))}
                    />
                ) : null}
                <SessionTimelineSection
                    timeline={timeline}
                    highlightMs={t === undefined ? undefined : t * 1000}
                    onOpenIssue={openIssue}
                />
            </ScrollView>
            <SessionChrome
                title={scrollTitle.title}
                onBack={onBack}
                onOpenFull={safeWebUrl ? openFull : null}
                onMore={() => setMenuOpen(true)}
            />
            <Pressable44
                onPress={openChat}
                accessibilityLabel="Chat about this session"
                pressedBackground={colors.inkHover}
                style={[styles.chat, shadows.fab, { bottom: bottomOffset(insets, 34) }]}
                haptic="selection"
                testID="session-chat"
            >
                <ComposeIcon size={iconSizes.navigation} color={colors.onInk} />
            </Pressable44>
            <HeaderMenu
                visible={menuOpen}
                onClose={() => setMenuOpen(false)}
                testID="session-menu"
                items={[
                    {
                        key: 'share',
                        label: `Share link at ${formatOffset(seconds * 1000)}`,
                        Icon: ExternalLinkIcon,
                        onPress: share,
                        disabled: !safeWebUrl,
                    },
                    { key: 'copy', label: 'Copy session ID', Icon: CopyIcon, onPress: copyId },
                ]}
            />
            {summary ? (
                <FrameSheet
                    observationId={summary.observationId}
                    chapters={chapters}
                    position={framePosition}
                    onChangePosition={setFramePosition}
                    onClose={() => setFramePosition(null)}
                />
            ) : null}
            <ViewsToast toast={toasts.toast} onHide={toasts.hide} bottom={110} />
        </View>
    )
}

/** Sends the opened event once, when it can say whether the session has a summary. */
function useOpenedEvent(sessionId: string, source: SessionOpenSource, flow: SessionSummaryFlow): void {
    const sent = useRef<string | null>(null)
    const settled = flow.card.kind !== 'loading'
    const hasSummary = flow.summary !== null
    useEffect(() => {
        if (settled && sent.current !== sessionId) {
            sent.current = sessionId
            trackSessionOpened({ sessionId, source, hasSummary })
        }
    }, [settled, sessionId, source, hasSummary])
}

interface HeaderProps {
    onTitleLayout: ScrollTitleState['onTitleLayout']
    recording: RecordingView
    timeline: QueryState<SessionTimeline>
    projectName: string
    title: string | null
    keyMomentMs: number | null
    onKeyMoment: (() => void) | null
}

function Header({
    recording,
    timeline,
    projectName,
    title,
    keyMomentMs,
    onKeyMoment,
    onTitleLayout,
}: HeaderProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const events = timeline.data ?? null
    const started = recording.startedAt ? new Date(recording.startedAt) : null
    const meta = [
        recording.personLabel,
        started ? `${formatMonthDay(started)}, ${formatClock(started)}` : null,
        formatDuration(recording.durationSeconds),
        events?.device ?? null,
        recording.ongoing ? 'Still recording' : null,
    ].filter((part): part is string => Boolean(part))
    const firstError = events?.firstExceptionMs ?? null
    return (
        <View>
            <View onLayout={onTitleLayout}>
                <View style={styles.eyebrowRow}>
                    <RecordingIcon size={iconSizes.small} color={colors.tertiary} />
                    <Text style={styles.eyebrow} numberOfLines={1}>
                        {projectName ? `Session · ${projectName}` : 'Session'}
                    </Text>
                </View>
                <Text style={[styles.title, prettyWrap]} lineBreakStrategyIOS="standard" accessibilityRole="header">
                    {title ?? fallbackTitle(recording, events)}
                </Text>
            </View>
            <Text style={styles.meta}>{meta.join(' · ')}</Text>
            <View style={styles.chips}>
                {keyMomentMs !== null ? (
                    <Chip
                        icon={<FlagIcon size={iconSizes.small} color={colors.orange} />}
                        label={`Key moment ${formatOffset(keyMomentMs)}`}
                        alert
                        onPress={onKeyMoment}
                        testID="session-key-moment"
                    />
                ) : firstError !== null ? (
                    <Chip
                        icon={<WarningIcon size={iconSizes.small} color={colors.orange} />}
                        label={`First error ${formatOffset(firstError)}`}
                        alert
                        testID="session-first-error"
                    />
                ) : null}
                {events?.city ? (
                    <Chip icon={<GlobeIcon size={iconSizes.small} />} label={events.city} testID="session-city" />
                ) : null}
            </View>
        </View>
    )
}

interface ChipProps {
    icon: ReactElement
    label: string
    alert?: boolean
    onPress?: (() => void) | null
    testID: string
}

function Chip({ icon, label, alert = false, onPress, testID }: ChipProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const content = (
        <>
            {icon}
            <Text style={[styles.chipText, alert && styles.chipTextAlert]}>{label}</Text>
        </>
    )
    if (!onPress) {
        return (
            <View style={[styles.chip, alert && styles.chipAlert]} testID={testID}>
                {content}
            </View>
        )
    }
    return (
        <Pressable44
            onPress={onPress}
            accessibilityRole="button"
            accessibilityLabel={label}
            pressedBackground={colors.sunken}
            style={[styles.chip, alert && styles.chipAlert]}
            testID={testID}
        >
            {content}
        </Pressable44>
    )
}

const useStyles = createStyles(({ colors }) => ({
    screen: {
        flex: 1,
        backgroundColor: colors.background,
    },
    fill: {
        flex: 1,
    },
    content: {
        paddingHorizontal: layout.detailGutter,
    },
    eyebrowRow: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 6,
    },
    eyebrow: {
        ...type.eyebrow,
        textTransform: 'uppercase',
        color: colors.tertiary,
        flexShrink: 1,
    },
    title: {
        ...type.headline,
        color: colors.ink,
        marginTop: 8,
    },
    meta: {
        ...type.metaSmall,
        color: colors.secondary,
        marginTop: 8,
    },
    chips: {
        flexDirection: 'row',
        flexWrap: 'wrap',
        gap: 8,
        marginTop: 12,
    },
    chip: {
        height: 32,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 6,
        paddingHorizontal: 12,
        borderRadius: radii.pill,
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: colors.surface,
    },
    chipAlert: {
        borderColor: colors.orangeLight,
    },
    chipText: {
        ...type.meta,
        fontWeight: '500',
        color: colors.ink,
    },
    chipTextAlert: {
        color: colors.orange,
    },
    chat: {
        position: 'absolute',
        right: layout.actionBarGutter,
        width: 54,
        height: 54,
        borderRadius: radii.pill,
        backgroundColor: colors.ink,
        alignItems: 'center',
        justifyContent: 'center',
    },
}))
