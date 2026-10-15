import { useQueryClient } from '@tanstack/react-query'
import { useRouter } from 'expo-router'
import { type ReactElement, useEffect, useState } from 'react'
import { StyleSheet, View } from 'react-native'
import Animated, { useAnimatedScrollHandler, useSharedValue } from 'react-native-reanimated'

import { useProjectScope } from '@/auth/useProjectScope'
import { useViewer } from '@/auth/useViewer'
import { useDataMode } from '@/demo/demoMode'
import { track } from '@/lib/analytics'
import { isReportId } from '@/lib/ids'
import type { ReportPriority, ReportView, SnoozeChoice } from '@/model/types'
import { WarningIcon } from '@/ui/icons/WarningIcon'
import { OverlayHost } from '@/ui/OverlayPortal'
import { LoadingView, StateView } from '@/ui/StateView'
import { colors, iconSizes, layout } from '@/ui/tokens'
import { topOffset, useScreenInsets } from '@/ui/useScreenInsets'

import { ActionBar } from '../handoff/ActionBar'
import { actionBarStateFor } from '../handoff/actionBarState'
import { HandoffSheet } from '../handoff/HandoffSheet'
import { useDecisionAnswer, useHandoffNotice } from '../handoff/hooks'
import { useReportWithLiveRun } from '../handoff/useReportWithLiveRun'
import { useInboxItems, useMarkReadOnOpen } from '../inbox/hooks'
import { PrioritySheet } from '../priority/PrioritySheet'
import { AssigneeSheet } from '../reviewers/AssigneeSheet'
import { useGithubOnlyReviewerCount } from '../reviewers/hooks'
import { SnoozeSheet } from '../snooze/SnoozeSheet'
import { Activity } from './Activity'
import { Evidence } from './Evidence'
import { Facts } from './Facts'
import { Headline, headlineText } from './Headline'
import { useReportActions, useReportNeighbors } from './hooks'
import { ImpactMetrics } from './metrics/ImpactMetrics'
import { ObservationCard } from './metrics/ObservationCard'
import { ReportCharts } from './metrics/ReportCharts'
import { reportDetailQuery } from './queries'
import { ReportMeta } from './ReportMeta'
import { TOP_CHROME_BOTTOM, TopChrome } from './TopChrome'

type Overlay = 'none' | 'handoff' | 'snooze' | 'assignee' | 'priority'

const CONTENT_TOP = 116
/** The gap between the chrome and the headline at rest, so the title reveal ends as the headline fully passes under. */
const HEADLINE_GAP = CONTENT_TOP - TOP_CHROME_BOTTOM

interface ReportScreenProps {
    reportId: string
}

function goBackOrInbox(router: ReturnType<typeof useRouter>): void {
    if (router.canGoBack()) {
        router.back()
    } else {
        router.replace('/inbox')
    }
}

export function ReportScreen({ reportId }: ReportScreenProps): ReactElement {
    const demo = useDataMode() === 'demo'
    return (
        <OverlayHost>
            {isReportId(reportId, demo) ? <ReportContent reportId={reportId} /> : <ReportNotFound />}
        </OverlayHost>
    )
}

function ReportNotFound(): ReactElement {
    const router = useRouter()
    const goBack = (): void => goBackOrInbox(router)
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

function ReportContent({ reportId }: ReportScreenProps): ReactElement {
    const router = useRouter()
    const viewer = useViewer()
    const query = useReportWithLiveRun(reportId)
    const inbox = useInboxItems()
    const neighbors = useReportNeighbors(inbox, reportId)
    const actions = useReportActions(reportId)
    const answer = useDecisionAnswer(reportId)
    const notice = useHandoffNotice(reportId)
    const githubOnlyReviewers = useGithubOnlyReviewerCount(reportId)
    const [overlay, setOverlay] = useState<Overlay>('none')
    useMarkReadOnOpen(query.data?.id)
    const queryClient = useQueryClient()
    const scope = useProjectScope()
    const demo = useDataMode() === 'demo'

    // Read in the effect, before this screen's own fetch lands, so `from_cache` shows whether the inbox prefetch hit.
    // biome-ignore lint/correctness/useExhaustiveDependencies: one event per opened report, not per scope or mode change.
    useEffect(() => {
        const fromCache = !demo && queryClient.getQueryData(reportDetailQuery(scope, reportId).queryKey) !== undefined
        track('mobile_report_opened', { report_id: reportId, from_cache: fromCache })
    }, [reportId])

    const goBack = (): void => goBackOrInbox(router)
    const goTo = (id: string | undefined): (() => void) | undefined => (id ? () => router.setParams({ id }) : undefined)
    const closeOverlay = (): void => setOverlay('none')

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
    const openTaskChat = (): void => {
        if (taskId) {
            router.push({
                pathname: '/chat',
                params: { taskId, ...(task?.runId ? { runId: task.runId } : {}) },
            })
        }
    }
    const snooze = async (choice: SnoozeChoice): Promise<void> => {
        await actions.snooze(choice)
        closeOverlay()
        goBack()
    }
    const handOff = async (): Promise<void> => {
        await actions.handOff()
        closeOverlay()
    }
    const setPriority = async (priority: ReportPriority): Promise<void> => {
        await actions.setPriority(priority)
        closeOverlay()
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
                onReassign={() => setOverlay('assignee')}
                onChangePriority={() => setOverlay('priority')}
            />
            <ActionBar
                report={report}
                state={state}
                answer={answer}
                notice={notice}
                actions={actions}
                onOpenHandoff={() => setOverlay('handoff')}
                onReassign={() => setOverlay('assignee')}
                onSnooze={() => setOverlay('snooze')}
                onChat={() => router.push({ pathname: '/chat', params: { reportId: report.id } })}
                onTaskChat={taskId ? openTaskChat : undefined}
            />
            <HandoffSheet
                visible={overlay === 'handoff'}
                report={report}
                onClose={closeOverlay}
                onHandOff={() => void handOff()}
                pending={actions.pending.handOff}
            />
            <SnoozeSheet
                visible={overlay === 'snooze'}
                onClose={closeOverlay}
                onSnooze={snooze}
                pending={actions.pending.snooze}
            />
            <AssigneeSheet
                visible={overlay === 'assignee'}
                current={report.reviewers}
                githubOnlyCount={githubOnlyReviewers}
                onClose={closeOverlay}
                onSave={actions.setReviewers}
                pending={actions.pending.reviewers}
            />
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
}: ReportBodyProps): ReactElement {
    const insets = useScreenInsets()
    const [headlineHeight, setHeadlineHeight] = useState(0)
    const scrollY = useSharedValue(0)
    const onScroll = useAnimatedScrollHandler((event) => {
        scrollY.value = event.contentOffset.y
    })
    return (
        <View style={styles.body}>
            <Animated.ScrollView
                style={styles.scroll}
                contentContainerStyle={[styles.content, { paddingTop: topOffset(insets, CONTENT_TOP) }]}
                keyboardShouldPersistTaps="handled"
                onScroll={onScroll}
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
                <Evidence blocks={report.evidence} />
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

const styles = StyleSheet.create({
    screen: {
        flex: 1,
        backgroundColor: colors.background,
    },
    body: {
        flex: 1,
    },
    scroll: {
        flex: 1,
    },
    content: {
        paddingHorizontal: layout.detailGutter,
        paddingBottom: 28,
    },
})
