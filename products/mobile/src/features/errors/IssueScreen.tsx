import * as Clipboard from 'expo-clipboard'
import { useRouter } from 'expo-router'
import { type ReactElement, useEffect, useMemo, useRef, useState } from 'react'
import { Linking, RefreshControl, ScrollView, View } from 'react-native'
import { ApiError } from '@/api/client'
import type { ErrorsWindow, IssueApi, IssueStatusApi, WritableIssueStatus } from '@/api/errorTracking'
import { useViewer } from '@/auth/useViewer'
import { ISSUE_OBJECT_TYPE } from '@/features/chat/objectContext'
import { HeaderMenu } from '@/features/views/screen/HeaderMenu'
import { ViewChrome } from '@/features/views/screen/ViewChrome'
import { useViewBack } from '@/features/views/screen/ViewScreenFrame'
import { useFeatureAccess } from '@/features/views/useViewsAccess'
import { ViewsReauthState } from '@/features/views/ViewsReauthState'
import { useToasts, ViewsToast } from '@/features/views/ViewsToast'
import { actionErrorMessage } from '@/lib/errors'
import { safeHttpsUrl } from '@/lib/urls'
import { useNow } from '@/lib/useNow'
import { CopyIcon } from '@/ui/icons/CopyIcon'
import { ExternalLinkIcon } from '@/ui/icons/ExternalLinkIcon'
import { PersonIcon } from '@/ui/icons/PersonIcon'
import { WarningIcon } from '@/ui/icons/WarningIcon'
import { OverlayHost } from '@/ui/OverlayPortal'
import { LoadingView, StateView } from '@/ui/StateView'
import { SCREEN_CONTENT_TOP } from '@/ui/screenLayout'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, layout } from '@/ui/tokens'
import { topOffset, useScreenInsets } from '@/ui/useScreenInsets'
import { useScrollTitle } from '@/ui/useScrollTitle'
import {
    type IssueOpenSource,
    trackErrorsErrorShown,
    trackErrorsOpenedInWeb,
    trackIssueChatOpened,
    trackIssueFramesExpanded,
    trackIssueLinkCopied,
    trackIssueOpened,
    trackIssueSessionOpened,
} from './analytics'
import {
    useAssignToMeAction,
    useErrorsContext,
    useIssue,
    useIssueBreakdown,
    useIssueEvents,
    useIssueReport,
    useIssueSpiking,
    useIssueStatusAction,
    useIssueSummary,
    useRefreshIssue,
} from './hooks'
import { IssueActionBar } from './IssueActionBar'
import { IssueAssigneeSheet } from './IssueAssigneeSheet'
import {
    BreakdownCard,
    FramesCard,
    ImpactSection,
    IssueHeader,
    ReleaseCard,
    ReportLinkRow,
    Section,
    SessionRows,
} from './IssueSections'
import {
    assigneeFrom,
    badgeFor,
    breakdownRows,
    highlightStart,
    isIssueId,
    isNewInWindow,
    issueFrames,
    issueWebUrl,
    sampleSessions,
    trendCaption,
} from './issueModel'
import { SuppressSheet } from './SuppressSheet'

const MAX_FRAMES = 3
const MAX_SESSIONS = 3

type Overlay = 'none' | 'menu' | 'assign' | 'suppress'

interface IssueScreenProps {
    issueId: string
    from?: IssueOpenSource
    window?: ErrorsWindow
}

export function IssueScreen({ issueId, from = 'other', window = '24h' }: IssueScreenProps): ReactElement {
    const styles = useStyles()
    return (
        <OverlayHost>
            <View style={styles.screen} testID="issue-screen">
                <IssueGate issueId={issueId} from={from} window={window} />
            </View>
        </OverlayHost>
    )
}

function IssueGate({
    issueId,
    from,
    window,
}: {
    issueId: string
    from: IssueOpenSource
    window: ErrorsWindow
}): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const insets = useScreenInsets()
    const access = useFeatureAccess('errors')
    const { mode } = useErrorsContext()
    const goBack = useViewBack()
    const valid = isIssueId(issueId)
    useEffect(() => {
        if (!valid) {
            trackErrorsErrorShown({ kind: 'issue_not_found' })
        }
    }, [valid])

    let body: ReactElement | null = null
    if (access.state !== 'ok') {
        body = <ViewsReauthState access={access} feature="errors" />
    } else if (mode === 'demo') {
        body = (
            <StateView
                icon={<WarningIcon size={iconSizes.empty} color={colors.tertiary} />}
                title="Errors aren't in the demo"
                message="Sign in to see your project's error tracking issues."
                testID="issue-demo"
            />
        )
    } else if (mode === 'loading') {
        body = <LoadingView label="Loading the issue" />
    } else if (!valid) {
        body = (
            <StateView
                icon={<WarningIcon size={iconSizes.empty} color={colors.tertiary} />}
                title="Couldn't find this issue"
                message="This link doesn't point to an error tracking issue. Go back and open it from the errors list."
                actionLabel="Go back"
                onAction={goBack}
                testID="issue-not-found"
            />
        )
    }
    if (body) {
        return (
            <>
                <View style={[styles.fill, { paddingTop: topOffset(insets, SCREEN_CONTENT_TOP) }]}>{body}</View>
                <ViewChrome onBack={goBack} />
            </>
        )
    }
    return <IssueContent issueId={issueId} from={from} window={window} onBack={goBack} />
}

function IssueContent({
    issueId,
    from,
    window,
    onBack,
}: {
    issueId: string
    from: IssueOpenSource
    window: ErrorsWindow
    onBack: () => void
}): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const insets = useScreenInsets()
    const issue = useIssue(issueId)
    const missing = issue.error instanceof ApiError && issue.error.status === 404
    const failed = issue.isError && !issue.data
    useEffect(() => {
        if (failed) {
            trackErrorsErrorShown({ kind: missing ? 'issue_not_found' : 'issue_failed' })
        }
    }, [failed, missing])

    if (issue.data) {
        return <IssueLoaded issue={issue.data} from={from} initialWindow={window} onBack={onBack} />
    }
    return (
        <>
            <View style={[styles.fill, { paddingTop: topOffset(insets, SCREEN_CONTENT_TOP) }]}>
                {failed ? (
                    <StateView
                        icon={<WarningIcon size={iconSizes.empty} color={colors.tertiary} />}
                        title={missing ? "Couldn't find this issue" : "Couldn't load this issue"}
                        message={
                            missing
                                ? 'It may have been merged into another issue or belong to another project.'
                                : 'Check your connection and try again.'
                        }
                        actionLabel={missing ? 'Go back' : 'Try again'}
                        onAction={missing ? onBack : () => issue.refetch()}
                        testID={missing ? 'issue-not-found' : 'issue-error'}
                    />
                ) : (
                    <LoadingView label="Loading the issue" />
                )}
            </View>
            <ViewChrome onBack={onBack} />
        </>
    )
}

const STATUS_TOAST: Record<WritableIssueStatus, string> = {
    resolved: 'Issue resolved',
    suppressed: 'Issue suppressed',
    active: 'Issue reopened',
}

function IssueLoaded({
    issue,
    from,
    initialWindow,
    onBack,
}: {
    issue: IssueApi
    from: IssueOpenSource
    initialWindow: ErrorsWindow
    onBack: () => void
}): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const router = useRouter()
    const insets = useScreenInsets()
    const now = useNow()
    const viewer = useViewer()
    const { scope, myUserId } = useErrorsContext()
    const toasts = useToasts()
    const [window, setWindow] = useState<ErrorsWindow>(initialWindow)
    const [overlay, setOverlay] = useState<Overlay>('none')
    const [framesExpanded, setFramesExpanded] = useState(false)
    const [pulling, setPulling] = useState(false)
    const [assignError, setAssignError] = useState<string | null>(null)

    const summary = useIssueSummary(issue.id, window)
    const events = useIssueEvents(issue.id, window)
    const breakdown = useIssueBreakdown(issue.id, window)
    const report = useIssueReport(issue.id)
    const spiking = useIssueSpiking(issue.id, window)
    const refresh = useRefreshIssue(issue.id)
    const statusAction = useIssueStatusAction(issue.id)
    const assignAction = useAssignToMeAction(issue.id)

    // Sent once per visit, with the status the screen first showed.
    const opened = useRef(false)
    useEffect(() => {
        if (!opened.current) {
            opened.current = true
            trackIssueOpened({ source: from, status: issue.status })
        }
    }, [from, issue.status])

    const title = issue.name?.trim() || 'Unnamed error'
    const assignee = assigneeFrom(issue.assignee, myUserId)
    const isNew = isNewInWindow(issue.first_seen, window, now)
    const badge = badgeFor(isNew, spiking)
    const volume = summary.data?.sparkline ?? []
    const caption = trendCaption(summary.data?.trend)
    const highlight = highlightStart(volume, badge ?? (caption?.rising ? 'spiking' : null))
    const frames = useMemo(() => issueFrames(events.data?.results ?? [], MAX_FRAMES), [events.data])
    const sessions = useMemo(() => sampleSessions(events.data?.results ?? [], MAX_SESSIONS), [events.data])
    const breakdownList = useMemo(() => breakdownRows(breakdown.data), [breakdown.data])
    const webUrl = issueWebUrl(scope, issue.id)
    const safeWebUrl = webUrl ? safeHttpsUrl(webUrl) : undefined
    const impact = summary.data?.impact

    const setStatus = (to: WritableIssueStatus, undo: boolean): void => {
        const previous: IssueStatusApi = issue.status
        const back: WritableIssueStatus = previous === 'resolved' || previous === 'suppressed' ? previous : 'active'
        statusAction
            .run({
                to,
                undo,
                onSaved: undo ? undefined : () => toasts.show(STATUS_TOAST[to], () => setStatus(back, true)),
            })
            .catch(() => {
                trackErrorsErrorShown({ kind: 'status_failed' })
                toasts.show("Couldn't update the issue. Try again.")
            })
            .finally(() => setOverlay((current) => (current === 'suppress' ? 'none' : current)))
    }
    const assignMe = (assign: boolean): void => {
        setAssignError(null)
        assignAction
            .run(assign, () => {
                setOverlay('none')
                toasts.show(assign ? 'Assigned to you' : 'Unassigned')
            })
            .catch((error: unknown) => {
                trackErrorsErrorShown({ kind: 'assign_failed' })
                setAssignError(actionErrorMessage(error))
            })
    }
    const openWeb = safeWebUrl
        ? (): void => {
              trackErrorsOpenedInWeb({ screen: 'issue' })
              Linking.openURL(safeWebUrl).catch(() => undefined)
          }
        : undefined
    const openChat = (): void => {
        trackIssueChatOpened()
        router.push({
            pathname: '/chat',
            params: { entry: 'issue', objectType: ISSUE_OBJECT_TYPE, objectId: issue.id, objectLabel: title },
        })
    }
    const onPull = (): void => {
        setPulling(true)
        refresh().finally(() => setPulling(false))
    }

    const heading = issue.description ? `${title}: ${issue.description}` : title
    const scrollTitle = useScrollTitle(heading)

    return (
        <>
            <ScrollView
                style={styles.fill}
                contentContainerStyle={[styles.content, { paddingTop: topOffset(insets, SCREEN_CONTENT_TOP) }]}
                refreshControl={
                    <RefreshControl
                        refreshing={pulling}
                        onRefresh={onPull}
                        tintColor={colors.tertiary}
                        progressBackgroundColor={colors.surface}
                        colors={[colors.tertiary]}
                        progressViewOffset={topOffset(insets, SCREEN_CONTENT_TOP)}
                    />
                }
                onScroll={scrollTitle.onScroll}
                scrollEventThrottle={16}
                testID="issue-scroll"
            >
                <IssueHeader
                    onTitleLayout={scrollTitle.onTitleLayout}
                    eyebrow={viewer.projectName ? `Error · ${viewer.projectName}` : 'Error'}
                    status={issue.status}
                    badge={badge}
                    name={title}
                    description={issue.description}
                    firstSeen={issue.first_seen}
                    lastSeen={summary.data?.last_seen ?? null}
                    now={now}
                    assignee={assignee}
                    myName={viewer.name}
                    onAssign={() => {
                        setAssignError(null)
                        setOverlay('assign')
                    }}
                />
                <ImpactSection
                    window={window}
                    onWindow={setWindow}
                    loading={summary.isLoading}
                    users={impact?.users ?? null}
                    sessions={impact?.sessions ?? null}
                    occurrences={impact?.occurrences ?? null}
                    volume={volume}
                    highlightFrom={highlight}
                    caption={caption}
                />
                <ReleaseCard
                    latest={summary.data?.latest_release}
                    first={summary.data?.first_release}
                    library={summary.data?.library ?? null}
                />
                <Section title="Where it breaks">
                    <FramesCard
                        heading={heading}
                        frames={frames.frames}
                        total={frames.total}
                        loading={events.isLoading}
                        expanded={framesExpanded}
                        onToggle={() => {
                            if (!framesExpanded) {
                                trackIssueFramesExpanded({ frames: frames.frames.length })
                            }
                            setFramesExpanded(!framesExpanded)
                        }}
                    />
                    <BreakdownCard rows={breakdownList} />
                </Section>
                {sessions.length > 0 ? (
                    <Section title="Sessions">
                        <SessionRows
                            sessions={sessions}
                            now={now}
                            onOpen={(session, position) => {
                                trackIssueSessionOpened({ position })
                                router.push({
                                    pathname: '/replay/[sessionId]',
                                    // No `t`: the event has an absolute time, and the offset needs the recording's start.
                                    params: { sessionId: session.sessionId, source: 'issue' },
                                })
                            }}
                        />
                    </Section>
                ) : null}
                {report ? (
                    <Section title="Inbox report">
                        <ReportLinkRow
                            title={report.title}
                            updatedAt={report.updatedAt}
                            now={now}
                            onOpen={() => router.push({ pathname: '/report/[id]', params: { id: report.id } })}
                        />
                    </Section>
                ) : null}
            </ScrollView>
            <ViewChrome title={scrollTitle.title} onBack={onBack} onMore={() => setOverlay('menu')} />
            <IssueActionBar
                active={issue.status === 'active'}
                pending={statusAction.pending}
                onResolve={() => setStatus('resolved', false)}
                onSuppress={() => setOverlay('suppress')}
                onReopen={() => setStatus('active', false)}
                onChat={openChat}
            />
            <HeaderMenu
                visible={overlay === 'menu'}
                onClose={() => setOverlay('none')}
                testID="issue-menu"
                items={[
                    {
                        key: 'assign',
                        label: 'Assign',
                        Icon: PersonIcon,
                        onPress: () => {
                            setAssignError(null)
                            setOverlay('assign')
                        },
                    },
                    {
                        key: 'web',
                        label: 'Open on web',
                        Icon: ExternalLinkIcon,
                        disabled: !openWeb,
                        onPress: () => openWeb?.(),
                    },
                    {
                        key: 'copy',
                        label: 'Copy link',
                        Icon: CopyIcon,
                        disabled: !safeWebUrl,
                        onPress: () => {
                            if (!safeWebUrl) {
                                return
                            }
                            Clipboard.setStringAsync(safeWebUrl)
                                .then(() => {
                                    trackIssueLinkCopied()
                                    toasts.show('Link copied')
                                })
                                .catch(() => toasts.show("Couldn't copy the link"))
                        },
                    },
                ]}
            />
            <IssueAssigneeSheet
                visible={overlay === 'assign'}
                assignee={assignee}
                myName={viewer.name}
                pending={assignAction.pending}
                canAssign={myUserId !== null}
                error={assignError}
                onClose={() => setOverlay('none')}
                onAssignMe={assignMe}
                onOpenWeb={openWeb}
            />
            <SuppressSheet
                visible={overlay === 'suppress'}
                pending={statusAction.pending}
                onClose={() => setOverlay('none')}
                onConfirm={() => setStatus('suppressed', false)}
            />
            <ViewsToast toast={toasts.toast} onHide={toasts.hide} />
        </>
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
        paddingBottom: 28,
    },
}))
