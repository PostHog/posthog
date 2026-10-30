import { useRouter } from 'expo-router'
import { type ReactElement, useEffect, useRef, useState } from 'react'
import { Text, View } from 'react-native'
import Animated, { useAnimatedScrollHandler, useSharedValue } from 'react-native-reanimated'
import { useDataMode } from '@/demo/demoMode'
import { track } from '@/lib/analytics'
import { isReportId } from '@/lib/ids'
import type { ReportView } from '@/model/types'
import { WarningIcon } from '@/ui/icons/WarningIcon'
import { LoadingView, StateView } from '@/ui/StateView'
import { SCREEN_CONTENT_TOP } from '@/ui/screenLayout'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, layout, type } from '@/ui/tokens'
import { bottomOffset, topOffset, useScreenInsets } from '@/ui/useScreenInsets'

import { headlineText } from '../Headline'
import { useReport } from '../hooks'
import { HEADLINE_GAP, TopChrome } from '../TopChrome'
import { useReportReadTracking } from '../useReportReadTracking'
import { DetailsFooter } from './DetailsFooter'
import { DetailsHeader } from './DetailsHeader'
import { DetailsSummary } from './DetailsSummary'
import { hasReportDetail } from './hasReportDetail'
import { SignalsSection } from './SignalsSection'

const CONTENT_BOTTOM = 62

interface ReportDetailsScreenProps {
    reportId: string
}

export function ReportDetailsScreen({ reportId }: ReportDetailsScreenProps): ReactElement {
    const styles = useStyles()
    const colors = useColors()
    const router = useRouter()
    const demo = useDataMode() === 'demo'
    const valid = isReportId(reportId, demo)
    // A deep link can open this screen with nothing under it, so Back then lands on the report itself.
    const goBack = (): void => {
        if (router.canGoBack()) {
            router.back()
        } else if (valid) {
            router.replace({ pathname: '/report/[id]', params: { id: reportId } })
        } else {
            router.replace('/inbox')
        }
    }
    return (
        <View style={styles.screen} testID="report-details-screen">
            {valid ? (
                <DetailsContent reportId={reportId} onBack={goBack} />
            ) : (
                <>
                    <TopChrome onBack={goBack} withPager={false} />
                    <StateView
                        icon={<WarningIcon size={iconSizes.empty} color={colors.tertiary} />}
                        title="Couldn't find this report"
                        message="This link doesn't point to a report. Go back and open the report from your inbox."
                        actionLabel="Go back"
                        onAction={goBack}
                        testID="report-details-not-found"
                    />
                </>
            )}
        </View>
    )
}

function DetailsContent({ reportId, onBack }: { reportId: string; onBack: () => void }): ReactElement {
    const colors = useColors()
    // Not the polling read: it shares the report screen's cache, so the report shows at once and refreshes once.
    const query = useReport(reportId)
    const report = query.data
    const opened = useRef(false)
    useEffect(() => {
        if (report && !opened.current) {
            opened.current = true
            track('mobile_report_details_opened', {
                report_id: report.id,
                has_summary: Boolean(report.summary),
                signal_count: report.signals.length,
            })
        }
    }, [report])

    if (!report) {
        return (
            <>
                <TopChrome onBack={onBack} withPager={false} />
                {query.isLoading ? (
                    <LoadingView label="Loading the report" />
                ) : (
                    <StateView
                        icon={<WarningIcon size={iconSizes.empty} color={colors.tertiary} />}
                        title="Couldn't load this report"
                        message={query.error?.message ?? 'Check your connection and try again.'}
                        actionLabel="Try again"
                        onAction={() => void query.refetch()}
                        testID="report-details-error"
                    />
                )}
            </>
        )
    }
    return <DetailsBody report={report} refreshing={query.isRefetching} onBack={onBack} />
}

interface DetailsBodyProps {
    report: ReportView
    refreshing: boolean
    onBack: () => void
}

function DetailsBody({ report, refreshing, onBack }: DetailsBodyProps): ReactElement {
    const styles = useStyles()
    const insets = useScreenInsets()
    const [headlineBottom, setHeadlineBottom] = useState(0)
    const scrollY = useSharedValue(0)
    const reading = useReportReadTracking(report.id, 'mobile_report_details_read')
    const { maxScrollY } = reading
    const onScroll = useAnimatedScrollHandler((event) => {
        scrollY.value = event.contentOffset.y
        maxScrollY.value = Math.max(maxScrollY.value, event.contentOffset.y)
    })
    return (
        <>
            <Animated.ScrollView
                style={styles.scroll}
                contentContainerStyle={[
                    styles.content,
                    {
                        paddingTop: topOffset(insets, SCREEN_CONTENT_TOP),
                        paddingBottom: bottomOffset(insets, CONTENT_BOTTOM),
                    },
                ]}
                onScroll={onScroll}
                onLayout={reading.onLayout}
                onContentSizeChange={reading.onContentSizeChange}
                scrollEventThrottle={16}
                testID="report-details-scroll"
            >
                <DetailsHeader report={report} onHeadlineBottom={setHeadlineBottom} />
                {hasReportDetail(report) ? (
                    <>
                        {report.summary ? <DetailsSummary summary={report.summary} reportId={report.id} /> : null}
                        <SignalsSection signals={report.signals} reportId={report.id} />
                    </>
                ) : (
                    <Text style={styles.empty} testID="report-details-empty">
                        This report has no more detail yet.
                    </Text>
                )}
                {report.webUrl ? <DetailsFooter webUrl={report.webUrl} reportId={report.id} /> : null}
            </Animated.ScrollView>
            <TopChrome
                refreshing={refreshing}
                onBack={onBack}
                withPager={false}
                title={{
                    text: headlineText(report.headline),
                    scrollY,
                    revealEnd: headlineBottom > 0 ? headlineBottom + HEADLINE_GAP : 0,
                }}
            />
        </>
    )
}

const useStyles = createStyles(({ colors }) => ({
    screen: {
        flex: 1,
        backgroundColor: colors.background,
    },
    scroll: {
        flex: 1,
    },
    content: {
        paddingHorizontal: layout.detailGutter,
    },
    empty: {
        ...type.body,
        marginTop: 24,
        color: colors.muted,
    },
}))
