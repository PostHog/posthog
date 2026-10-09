import { useRouter } from 'expo-router'
import { type ReactElement, useEffect, useState } from 'react'
import { ScrollView, StyleSheet, View } from 'react-native'

import { useViewer } from '@/auth/useViewer'
import { useDataMode } from '@/demo/demoMode'
import { track } from '@/lib/analytics'
import { isReportId } from '@/lib/ids'
import type { SnoozeChoice } from '@/model/types'
import { WarningIcon } from '@/ui/icons/WarningIcon'
import { Sparkline } from '@/ui/Sparkline'
import { LoadingView, StateView } from '@/ui/StateView'
import { colors, layout } from '@/ui/tokens'
import { topOffset, useScreenInsets } from '@/ui/useScreenInsets'

import { ActionBar } from '../handoff/ActionBar'
import { actionBarStateFor } from '../handoff/actionBarState'
import { HandoffSheet } from '../handoff/HandoffSheet'
import { useDecisionAnswer, useHandoffNotice } from '../handoff/hooks'
import { useReportWithLiveRun } from '../handoff/useReportWithLiveRun'
import { useInboxItems, useMarkReadOnOpen } from '../inbox/hooks'
import { AssigneeSheet } from '../reviewers/AssigneeSheet'
import { useGithubOnlyReviewerCount } from '../reviewers/hooks'
import { SnoozeSheet } from '../snooze/SnoozeSheet'
import { Activity } from './Activity'
import { Evidence } from './Evidence'
import { Facts } from './Facts'
import { Headline } from './Headline'
import { useReportActions, useReportNeighbors } from './hooks'
import { TopChrome } from './TopChrome'

type Overlay = 'none' | 'handoff' | 'snooze' | 'assignee'

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
    return isReportId(reportId, demo) ? <ReportContent reportId={reportId} /> : <ReportNotFound />
}

function ReportNotFound(): ReactElement {
    const router = useRouter()
    const goBack = (): void => goBackOrInbox(router)
    return (
        <View style={styles.screen}>
            <TopChrome onBack={goBack} />
            <StateView
                icon={<WarningIcon size={28} color={colors.tertiary} />}
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
    const insets = useScreenInsets()
    const viewer = useViewer()
    const query = useReportWithLiveRun(reportId)
    const inbox = useInboxItems()
    const neighbors = useReportNeighbors(inbox.data, reportId)
    const actions = useReportActions(reportId)
    const answer = useDecisionAnswer(reportId)
    const notice = useHandoffNotice(reportId)
    const githubOnlyReviewers = useGithubOnlyReviewerCount(reportId)
    const [overlay, setOverlay] = useState<Overlay>('none')
    useMarkReadOnOpen(reportId)

    useEffect(() => {
        track('mobile_report_opened', { report_id: reportId })
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
                        icon={<WarningIcon size={28} color={colors.tertiary} />}
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
    const snooze = async (choice: SnoozeChoice): Promise<void> => {
        await actions.snooze(choice)
        closeOverlay()
        goBack()
    }
    const handOff = async (): Promise<void> => {
        await actions.handOff()
        closeOverlay()
    }

    return (
        <View style={styles.screen} testID="report-screen">
            <View style={styles.body}>
                <ScrollView
                    key={report.id}
                    style={styles.scroll}
                    contentContainerStyle={[styles.content, { paddingTop: topOffset(insets, 116) }]}
                    keyboardShouldPersistTaps="handled"
                    testID="report-scroll"
                >
                    <Headline headline={report.headline} accent={report.accent} lede={report.lede} />
                    <Evidence blocks={report.evidence} />
                    <Facts facts={report.facts} />
                    {report.metric ? (
                        <View style={styles.metric}>
                            <Sparkline metric={report.metric} accent={report.accent} />
                        </View>
                    ) : null}
                    <Activity events={report.activity} viewerName={viewer.name} />
                </ScrollView>
                <TopChrome onBack={goBack} onPrevious={goTo(neighbors.previousId)} onNext={goTo(neighbors.nextId)} />
            </View>
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
    metric: {
        marginTop: 24,
    },
})
