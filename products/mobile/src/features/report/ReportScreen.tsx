import { useQueryClient } from '@tanstack/react-query'
import { useRouter } from 'expo-router'
import { type ReactElement, useEffect, useState } from 'react'
import { View } from 'react-native'
import Animated, { useAnimatedScrollHandler, useSharedValue } from 'react-native-reanimated'
import { useProjectScope } from '@/auth/useProjectScope'
import { useViewer } from '@/auth/useViewer'
import { useDataMode } from '@/demo/demoMode'
import type { ChatSheetEntry } from '@/features/chat/chatSheetEvents'
import { track } from '@/lib/analytics'
import { isReportId } from '@/lib/ids'
import type { ReportPriority, ReportView } from '@/model/types'
import {
    DISMISSAL_REASON_OPTIONS,
    type DismissReason,
    RESOLVE_REASON_OPTIONS,
    type ResolveReason,
} from '@/model/verdictReasons'
import { FloatingCard } from '@/ui/FloatingCard'
import { WarningIcon } from '@/ui/icons/WarningIcon'
import { OverlayHost } from '@/ui/OverlayPortal'
import { LoadingView, StateView } from '@/ui/StateView'
import { SCREEN_CONTENT_TOP } from '@/ui/screenLayout'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, layout } from '@/ui/tokens'
import { topOffset, useScreenInsets } from '@/ui/useScreenInsets'

import { ActionBar, type TaskChatEntry } from '../handoff/ActionBar'
import { actionBarStateFor } from '../handoff/actionBarState'
import { HandoffSheet } from '../handoff/HandoffSheet'
import { useDecisionAnswer, useHandoffNotice } from '../handoff/hooks'
import { useReportWithLiveRun } from '../handoff/useReportWithLiveRun'
import { useInboxItems, useMarkReadOnOpen } from '../inbox/hooks'
import { useInboxFilters } from '../inbox/inboxFiltersStore'
import { PrioritySheet } from '../priority/PrioritySheet'
import { AssigneeSheet } from '../reviewers/AssigneeSheet'
import { useGithubOnlyReviewerCount, useReportReviewersQuery } from '../reviewers/hooks'
import { VerdictSheet } from '../verdict/VerdictSheet'
import { dismissCopy, hasOpenPullRequest, resolveCopy } from '../verdict/verdictCopy'
import { Activity } from './Activity'
import { hasReportDetail } from './details/hasReportDetail'
import { Evidence } from './Evidence'
import { Facts } from './Facts'
import { Headline, headlineText } from './Headline'
import { useReportActions, useReportNeighbors } from './hooks'
import { ImpactMetrics } from './metrics/ImpactMetrics'
import { ObservationCard } from './metrics/ObservationCard'
import { ReportCharts } from './metrics/ReportCharts'
import { reportDetailQuery } from './queries'
import { ReportMeta } from './ReportMeta'
import { apiErrorKind, type ReportOpenSource, type SheetEntry, useSheetFunnel } from './reportAnalytics'
import { TextLinkRow } from './TextLinkRow'
import { HEADLINE_GAP, TopChrome } from './TopChrome'
import { useReportReadTracking } from './useReportReadTracking'

type Sheet = 'handoff' | 'resolve' | 'dismiss' | 'assignee' | 'priority'
type Overlay = 'none' | Sheet

interface ReportScreenProps {
    reportId: string
    from: ReportOpenSource
}

function goBackOrInbox(router: ReturnType<typeof useRouter>): void {
    if (router.canGoBack()) {
        router.back()
    } else {
        router.replace('/inbox')
    }
}

export function ReportScreen({ reportId, from }: ReportScreenProps): ReactElement {
    const demo = useDataMode() === 'demo'
    return (
        <OverlayHost>
            {isReportId(reportId, demo) ? <ReportContent reportId={reportId} from={from} /> : <ReportNotFound />}
        </OverlayHost>
    )
}

function ReportNotFound(): ReactElement {
    const styles = useStyles()
    const colors = useColors()
    const router = useRouter()
    const goBack = (): void => goBackOrInbox(router)
    // The id is not a report id and can be any text from a link, so it is not sent.
    useEffect(() => {
        track('mobile_report_load_failed', { kind: 'invalid_id' })
    }, [])
    return (
        <View style={styles.screen}>
            <TopChrome onBack={goBack} />
            <StateView
                icon={<WarningIcon size={iconSizes.empty} color={colors.tertiary} />}
                title="Couldn't find this report"
                message="This link doesn't point to a report. Go back and open the report from your inbox."
                actionLabel="Go back"
                onAction={goBack}
                testID="report-not-found"
            />
        </View>
    )
}

function ReportContent({ reportId, from }: ReportScreenProps): ReactElement {
    const styles = useStyles()
    const colors = useColors()
    const router = useRouter()
    const viewer = useViewer()
    const query = useReportWithLiveRun(reportId)
    // The same filters as the inbox, so Previous and Next follow the order the inbox shows.
    const inbox = useInboxItems({ filters: useInboxFilters() })
    const neighbors = useReportNeighbors(inbox, reportId)
    const actions = useReportActions(reportId)
    const answer = useDecisionAnswer(reportId)
    const notice = useHandoffNotice(reportId)
    const githubOnlyReviewers = useGithubOnlyReviewerCount(reportId)
    const reviewers = useReportReviewersQuery(reportId)
    const insets = useScreenInsets()
    const [overlay, setOverlay] = useState<Overlay>('none')
    const sheets = useSheetFunnel(reportId)
    useMarkReadOnOpen(query.data?.id)
    const queryClient = useQueryClient()
    const scope = useProjectScope()
    const demo = useDataMode() === 'demo'

    // Read in the effect, before this screen's own fetch lands, so `from_cache` shows whether the inbox prefetch hit.
    // biome-ignore lint/correctness/useExhaustiveDependencies: one event per opened report, not per scope or mode change.
    useEffect(() => {
        const fromCache = !demo && queryClient.getQueryData(reportDetailQuery(scope, reportId).queryKey) !== undefined
        track('mobile_report_opened', { report_id: reportId, from_cache: fromCache, from })
    }, [reportId])

    // A background refetch that fails keeps the cached report, so only a report that never loaded counts.
    const loadFailed = !query.data && query.isError
    // biome-ignore lint/correctness/useExhaustiveDependencies: one event each time the error screen appears.
    useEffect(() => {
        if (loadFailed) {
            track('mobile_report_load_failed', { report_id: reportId, kind: apiErrorKind(query.error) })
        }
    }, [loadFailed, reportId])

    const goBack = (): void => goBackOrInbox(router)
    const goTo = (id: string | undefined): (() => void) | undefined =>
        id ? () => router.setParams({ id, from: 'adjacent' }) : undefined
    const openSheet = (sheet: Sheet, entry: SheetEntry): void => {
        sheets.opened(sheet, entry)
        setOverlay(sheet)
    }
    const closeOverlay = (): void => {
        sheets.closed()
        setOverlay('none')
    }
    const completeOverlay = (): void => {
        sheets.completed()
        closeOverlay()
    }

    const report = query.data
    if (!report) {
        return (
            <View style={styles.screen}>
                <TopChrome onBack={goBack} />
                {query.isLoading ? (
                    <LoadingView label="Loading the report" />
                ) : (
                    <StateView
                        icon={<WarningIcon size={iconSizes.empty} color={colors.tertiary} />}
                        title="Couldn't load this report"
                        message={query.error?.message ?? 'Check your connection and try again.'}
                        actionLabel="Try again"
                        onAction={() => void query.refetch()}
                        testID="report-error"
                    />
                )}
            </View>
        )
    }

    const state = actionBarStateFor(report, { answer, handOffPending: actions.pending.handOff })
    const task = report.task
    const taskId = task?.taskId ?? report.work.assignee?.taskId
    const openTaskChat = (entry: TaskChatEntry): void => {
        if (taskId) {
            track('mobile_report_action_pressed', {
                action: 'task_chat',
                from: entry,
                report_id: report.id,
                run_status: task?.status,
            })
            router.push({
                pathname: '/chat',
                params: {
                    taskId,
                    entry: 'report_task' satisfies ChatSheetEntry,
                    ...(task?.runId ? { runId: task.runId } : {}),
                },
            })
        }
    }
    // A resolved or dismissed report leaves the inbox, so the screen goes back to it.
    const resolve = async (reason: ResolveReason, note: string): Promise<void> => {
        await actions.resolve(reason, note)
        completeOverlay()
        goBack()
    }
    const dismiss = async (reason: DismissReason, note: string): Promise<void> => {
        await actions.dismiss(reason, note)
        completeOverlay()
        goBack()
    }
    const title = headlineText(report.headline)
    const hasOpenPr = hasOpenPullRequest(state.pullRequests)
    // The sheet closes after a hand-off whether or not it starts, and `mobile_handoff_failed` records a failure,
    // so the attempt itself completes the sheet.
    const handOff = async (): Promise<void> => {
        sheets.completed()
        await actions.handOff()
        closeOverlay()
    }
    const setPriority = async (priority: ReportPriority): Promise<void> => {
        await actions.setPriority(priority)
        completeOverlay()
    }
    // The assignee sheet closes itself after a save, so the save only marks it complete.
    const setReviewers = async (uuids: string[]): Promise<void> => {
        await actions.setReviewers(uuids)
        sheets.completed()
    }
    const openChat = (): void => {
        track('mobile_report_action_pressed', { action: 'chat', from: 'action_bar', report_id: report.id })
        router.push({ pathname: '/chat', params: { reportId: report.id, entry: 'report' satisfies ChatSheetEntry } })
    }

    return (
        <View style={styles.screen} testID="report-screen">
            <ReportBody
                key={report.id}
                report={report}
                refreshing={query.isRefetching}
                viewerName={viewer.name}
                onBack={goBack}
                onPrevious={goTo(neighbors.previousId)}
                onNext={goTo(neighbors.nextId)}
                onReassign={() => openSheet('assignee', 'chip')}
                onChangePriority={() => openSheet('priority', 'chip')}
                onReadFull={() => router.push({ pathname: '/report/[id]/details', params: { id: report.id } })}
            />
            <ActionBar
                report={report}
                state={state}
                answer={answer}
                notice={notice}
                actions={actions}
                onOpenHandoff={() => openSheet('handoff', 'action_bar')}
                onReassign={() => openSheet('assignee', 'action_bar')}
                onResolve={() => openSheet('resolve', 'action_bar')}
                onDismiss={() => openSheet('dismiss', 'action_bar')}
                onChat={openChat}
                onTaskChat={taskId ? openTaskChat : undefined}
            />
            <HandoffSheet
                visible={overlay === 'handoff'}
                report={report}
                onClose={closeOverlay}
                onHandOff={() => void handOff()}
                onExternalHandoff={sheets.completed}
                pending={actions.pending.handOff}
            />
            <VerdictSheet
                visible={overlay === 'resolve'}
                copy={resolveCopy(title, hasOpenPr)}
                options={RESOLVE_REASON_OPTIONS}
                onClose={closeOverlay}
                onConfirm={resolve}
                pending={actions.pending.resolve}
                testID="resolve-sheet"
            />
            <VerdictSheet
                visible={overlay === 'dismiss'}
                copy={dismissCopy(title, hasOpenPr)}
                options={DISMISSAL_REASON_OPTIONS}
                onClose={closeOverlay}
                onConfirm={dismiss}
                pending={actions.pending.dismiss}
                testID="dismiss-sheet"
            />
            {reviewers.data ? (
                <AssigneeSheet
                    key={reportId}
                    visible={overlay === 'assignee'}
                    current={reviewers.data}
                    githubOnlyCount={githubOnlyReviewers}
                    onClose={closeOverlay}
                    onSave={setReviewers}
                    pending={actions.pending.reviewers}
                />
            ) : (
                <FloatingCard
                    visible={overlay === 'assignee'}
                    onClose={closeOverlay}
                    accessibilityLabel="Assignee"
                    testID="assignee-loading-sheet"
                    style={[styles.assigneeState, { top: topOffset(insets, 120) }]}
                >
                    {reviewers.isError ? (
                        <StateView
                            title="Couldn't load the assignees"
                            message="Check your connection and try again."
                            actionLabel="Try again"
                            onAction={() => void reviewers.refetch()}
                            testID="assignee-load-error"
                        />
                    ) : (
                        <LoadingView label="Loading the assignees" />
                    )}
                </FloatingCard>
            )}
            <PrioritySheet
                visible={overlay === 'priority'}
                current={report.priority}
                onClose={closeOverlay}
                onSelect={setPriority}
                pending={actions.pending.priority}
            />
        </View>
    )
}

interface ReportBodyProps {
    report: ReportView
    refreshing: boolean
    viewerName: string
    onBack: () => void
    onPrevious?: () => void
    onNext?: () => void
    onReassign: () => void
    onChangePriority: () => void
    onReadFull: () => void
}

// Keyed by report id from the parent, so the scroll offset and the measured headline start fresh for each report.
function ReportBody({
    report,
    refreshing,
    viewerName,
    onBack,
    onPrevious,
    onNext,
    onReassign,
    onChangePriority,
    onReadFull,
}: ReportBodyProps): ReactElement {
    const styles = useStyles()
    const insets = useScreenInsets()
    const [headlineHeight, setHeadlineHeight] = useState(0)
    const scrollY = useSharedValue(0)
    const reading = useReportReadTracking(report.id)
    const { maxScrollY } = reading
    const onScroll = useAnimatedScrollHandler((event) => {
        scrollY.value = event.contentOffset.y
        maxScrollY.value = Math.max(maxScrollY.value, event.contentOffset.y)
    })
    return (
        <View style={styles.body}>
            <Animated.ScrollView
                style={styles.scroll}
                contentContainerStyle={[styles.content, { paddingTop: topOffset(insets, SCREEN_CONTENT_TOP) }]}
                keyboardShouldPersistTaps="handled"
                onScroll={onScroll}
                onLayout={reading.onLayout}
                onContentSizeChange={reading.onContentSizeChange}
                scrollEventThrottle={16}
                testID="report-scroll"
            >
                <Headline
                    headline={report.headline}
                    accent={report.accent}
                    lede={report.lede}
                    meta={<ReportMeta report={report} onReassign={onReassign} onChangePriority={onChangePriority} />}
                    onHeadlineHeight={setHeadlineHeight}
                />
                {hasReportDetail(report) ? (
                    <View style={styles.readFull}>
                        <TextLinkRow label="Read the full report" onPress={onReadFull} testID="report-read-full" />
                    </View>
                ) : null}
                <Evidence blocks={report.evidence} reportId={report.id} />
                <Facts facts={report.facts} />
                {report.observation ? (
                    <ObservationCard metric={report.observation} reportId={report.id} accent={report.accent} />
                ) : null}
                <ImpactMetrics metrics={report.supportingMetrics} reportId={report.id} />
                <ReportCharts charts={report.charts} reportId={report.id} accent={report.accent} />
                <Activity events={report.activity} viewerName={viewerName} />
            </Animated.ScrollView>
            <TopChrome
                refreshing={refreshing}
                onBack={onBack}
                onPrevious={onPrevious}
                onNext={onNext}
                title={{
                    text: headlineText(report.headline),
                    scrollY,
                    revealEnd: headlineHeight > 0 ? headlineHeight + HEADLINE_GAP : 0,
                }}
            />
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    screen: {
        flex: 1,
        backgroundColor: colors.background,
    },
    body: {
        flex: 1,
    },
    assigneeState: {
        left: 16,
        right: 16,
        minHeight: 240,
    },
    scroll: {
        flex: 1,
    },
    content: {
        paddingHorizontal: layout.detailGutter,
        paddingBottom: 28,
    },
    readFull: {
        marginTop: 8,
    },
}))
