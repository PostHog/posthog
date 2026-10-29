import { type ReactElement, type ReactNode, useState } from 'react'
import { Linking, Text, View } from 'react-native'

import { useDataMode } from '@/demo/demoMode'
import { track } from '@/lib/analytics'
import { safeHttpsUrl } from '@/lib/urls'
import { useNow } from '@/lib/useNow'
import type { PullRequestView } from '@/model/types'
import { Dot } from '@/ui/Dot'
import { ChevronRightIcon } from '@/ui/icons/ChevronRightIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, radii, type } from '@/ui/tokens'

import { useSheetFunnel } from '../report/reportAnalytics'
import { PullRequestPickerSheet } from './PullRequestPickerSheet'
import { PULL_REQUEST_STATE_LABELS, pullRequestDetails, pullRequestIdentity } from './pullRequestDisplay'
import { usePullRequestChecks } from './usePullRequestChecks'

interface PullRequestCardProps {
    pullRequests: PullRequestView[]
    children?: ReactNode
    onTaskChat?: () => void
    reportId?: string
}

export function PullRequestCard({
    pullRequests,
    children,
    onTaskChat,
    reportId,
}: PullRequestCardProps): ReactElement | null {
    const colors = useColors()
    const styles = useStyles()
    const [selectedUrl, setSelectedUrl] = useState<string>()
    const [pickerOpen, setPickerOpen] = useState(false)
    const sheets = useSheetFunnel(reportId)
    const pullRequest = pullRequests.find((pr) => pr.url === selectedUrl) ?? pullRequests[0]
    const checks = usePullRequestChecks(reportId, pullRequest?.id)
    const now = useNow()
    const demo = useDataMode() === 'demo'
    if (!pullRequest) {
        return null
    }
    const identity = pullRequestIdentity(pullRequest)
    const details = pullRequestDetails(pullRequest)
    const checksStatus = demo && pullRequest.checksPassed === true ? 'passing' : checks.status
    const checksLabel = {
        checking: 'Checking CI',
        passing: 'Checks passed',
        failing: 'Checks failed',
        pending: 'Checks pending',
        none: 'No checks reported',
        unavailable: 'Checks unavailable',
    }[checksStatus]
    const checksColor = {
        checking: colors.blue,
        passing: colors.diffGreen,
        failing: colors.diffRed,
        pending: colors.yellow,
        none: colors.tertiary,
        unavailable: colors.yellow,
    }[checksStatus]
    const minutesSinceCheck =
        checks.observedAt === undefined
            ? undefined
            : Math.max(0, Math.floor((now.getTime() - checks.observedAt) / 60_000))
    const checkedAt =
        minutesSinceCheck === undefined
            ? undefined
            : minutesSinceCheck === 0
              ? 'Checked just now'
              : `Checked ${minutesSinceCheck}m ago`
    const url = safeHttpsUrl(pullRequest.url)
    const openPullRequest = (): void => {
        if (url) {
            track('mobile_pull_request_opened', {
                from: reportId ? 'report' : 'chat',
                report_id: reportId,
                state: pullRequest.state,
                pr_count: pullRequests.length,
            })
            Linking.openURL(url).catch(() => undefined)
        }
    }
    return (
        <View style={styles.card} testID="pr-ready-card">
            <View style={styles.heading}>
                <Text style={styles.label}>Pull request</Text>
                <Text style={styles.state} testID="pull-request-state">
                    {PULL_REQUEST_STATE_LABELS[pullRequest.state]}
                </Text>
                {pullRequests.length > 1 ? (
                    <Pressable44
                        onPress={() => {
                            sheets.opened('pull_request_picker', 'action_bar')
                            setPickerOpen(true)
                        }}
                        accessibilityLabel="Choose pull request"
                        pressedBackground={colors.pressed}
                        style={styles.selector}
                        testID="pull-request-selector"
                    >
                        <Text style={styles.selectorText}>{pullRequests.length} PRs</Text>
                        <ChevronRightIcon size={iconSizes.small} color={colors.muted} />
                    </Pressable44>
                ) : null}
            </View>
            <View style={styles.description}>
                {identity ? (
                    <Text style={styles.identity} numberOfLines={1}>
                        {identity}
                    </Text>
                ) : null}
                {pullRequest.title ? (
                    <Text style={styles.title} numberOfLines={2} testID="pull-request-title">
                        {pullRequest.title}
                    </Text>
                ) : null}
                {details ? (
                    <Text style={styles.details} numberOfLines={1}>
                        {details}
                    </Text>
                ) : null}
                <View style={styles.checks} testID="pull-request-checks">
                    <View style={styles.checksStatus}>
                        <Dot color={checksColor} />
                        <Text style={styles.details}>{checksLabel}</Text>
                    </View>
                    {checkedAt ? <Text style={styles.checkedAt}>{checkedAt}</Text> : null}
                </View>
            </View>
            {children ? <View style={styles.activity}>{children}</View> : null}
            <View style={styles.actions}>
                <Pressable44
                    onPress={openPullRequest}
                    disabled={!url}
                    accessibilityRole="link"
                    accessibilityLabel="View pull request"
                    pressedBackground={colors.blueHover}
                    style={[styles.button, styles.viewPr]}
                    testID="review-pr"
                >
                    <Text style={styles.viewPrText}>View PR</Text>
                </Pressable44>
                {onTaskChat ? (
                    <Pressable44
                        onPress={onTaskChat}
                        accessibilityLabel="View task activity in task chat"
                        pressedBackground={colors.pressed}
                        style={[styles.button, styles.viewTask]}
                        testID="view-task-activity"
                    >
                        <Text style={styles.viewTaskText}>View task activity</Text>
                    </Pressable44>
                ) : null}
            </View>
            <PullRequestPickerSheet
                visible={pickerOpen}
                pullRequests={pullRequests}
                selectedUrl={pullRequest.url}
                onClose={() => {
                    sheets.closed()
                    setPickerOpen(false)
                }}
                onSelect={(pr) => {
                    sheets.completed()
                    sheets.closed()
                    setSelectedUrl(pr.url)
                    setPickerOpen(false)
                }}
            />
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    card: {
        borderRadius: radii.card,
        backgroundColor: colors.surface,
        borderWidth: 1,
        borderColor: colors.hairline,
        overflow: 'hidden',
    },
    heading: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
        paddingTop: 10,
        paddingHorizontal: 12,
    },
    label: { ...type.metaSmall, fontWeight: '600', color: colors.ink },
    state: { ...type.meta, color: colors.muted, flexShrink: 1 },
    selector: { marginLeft: 'auto', flexDirection: 'row', alignItems: 'center', gap: 4, minHeight: 32 },
    selectorText: { ...type.meta, color: colors.muted },
    description: { gap: 3, paddingHorizontal: 12, paddingTop: 6, paddingBottom: 10 },
    identity: { ...type.meta, color: colors.secondary },
    title: { ...type.bodySmallStrong, color: colors.ink },
    details: { ...type.meta, color: colors.muted },
    checks: { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: 8 },
    checksStatus: { flexDirection: 'row', alignItems: 'center', gap: 6 },
    checkedAt: { ...type.meta, color: colors.tertiary },
    activity: { borderTopWidth: 1, borderTopColor: colors.hairline },
    actions: { flexDirection: 'row', gap: 8, padding: 10, borderTopWidth: 1, borderTopColor: colors.hairline },
    button: {
        flex: 1,
        minWidth: 0,
        minHeight: 44,
        borderRadius: radii.card,
        alignItems: 'center',
        justifyContent: 'center',
        paddingHorizontal: 6,
    },
    viewPr: { backgroundColor: colors.blue },
    viewTask: { backgroundColor: colors.background },
    // `onInk` reads on the blue fill in both schemes; white would be faint on the lighter dark-scheme blue.
    viewPrText: { ...type.buttonSmall, color: colors.onInk },
    viewTaskText: { ...type.metaSmall, fontWeight: '600', color: colors.ink, textAlign: 'center' },
}))
