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
                        loading: !metrics?.updatedAt,
                        value: metrics?.dailyActiveUsers ?? null,
                        about: 'Unique users active in the last 24 hours.',
                    },
                    {
                        key: 'wau',
                        label: 'WAU',
                        loading: !metrics?.updatedAt,
                        value: metrics?.weeklyActiveUsers ?? null,
                        about: 'Unique users active in the last 7 days.',
                    },
                    {
                        key: 'sessions',
                        label: 'Sessions',
                        loading: !metrics?.updatedAt,
                        value: metrics?.sessions ?? null,
                        about: 'Sessions active in the last 30 minutes.',
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
                        loading: !metrics?.updatedAt,
                        value: metrics?.installs ?? null,
                        about: 'First launches after install in the last 24 hours.',
                    },
                    {
                        key: 'installs-week',
                        label: 'Installs · 7d',
                        loading: !metrics?.updatedAt,
                        value: metrics?.weeklyInstalls ?? null,
                        about: 'First launches after install in the last 7 days.',
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
