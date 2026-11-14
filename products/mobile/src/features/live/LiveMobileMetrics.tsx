import type { ReactElement } from 'react'
import { Text, View } from 'react-native'

import type { LiveSnapshot } from '@/model/live'
import { createStyles } from '@/ui/theme'
import { type } from '@/ui/tokens'

import { LiveStats } from './LiveStats'

export function LiveMobileMetrics({
    metrics,
    onAbout,
}: {
    metrics: LiveSnapshot['mobileMetrics']
    onAbout: (text: string) => void
}): ReactElement {
    const styles = useStyles()
    return (
        <View style={styles.body} testID="live-mobile-metrics">
            <Text style={styles.heading} accessibilityRole="header">
                Mobile activity
            </Text>
            <LiveStats
                compact
                usersOnline={null}
                uniqueVisitors={null}
                pageviews={null}
                onAbout={onAbout}
                metrics={[
                    {
                        key: 'dau',
                        label: 'DAU',
                        value: metrics?.dailyActiveUsers ?? null,
                        about: 'Distinct mobile users active in the last 24 hours.',
                    },
                    {
                        key: 'wau',
                        label: 'WAU',
                        value: metrics?.weeklyActiveUsers ?? null,
                        about: 'Distinct mobile users active in the last 7 days.',
                    },
                    {
                        key: 'sessions',
                        label: 'Sessions',
                        value: metrics?.sessions ?? null,
                        about: 'Distinct mobile sessions with activity in the last 30 minutes. Requires session tracking.',
                    },
                ]}
            />
            <LiveStats
                compact
                usersOnline={null}
                uniqueVisitors={null}
                pageviews={null}
                onAbout={onAbout}
                metrics={[
                    {
                        key: 'installs-day',
                        label: 'Installs · 24h',
                        value: metrics?.installs ?? null,
                        about: 'Application Installed events in the last 24 hours. The SDK records the first launch after installation, rather than an app store download.',
                    },
                    {
                        key: 'installs-week',
                        label: 'Installs · 7d',
                        value: metrics?.weeklyInstalls ?? null,
                        about: 'Application Installed events in the last 7 days. The SDK records the first launch after installation, rather than an app store download.',
                    },
                ]}
            />
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    body: { gap: 8 },
    heading: { ...type.bodySmallStrong, color: colors.ink, paddingHorizontal: 6, marginTop: 4 },
}))
