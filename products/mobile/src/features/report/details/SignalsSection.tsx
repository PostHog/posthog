import type { ReactElement } from 'react'
import { Text, View } from 'react-native'
import { useNow } from '@/lib/useNow'
import { groupThousands } from '@/model/adapters/text'
import type { ReportSignalView } from '@/model/types'
import { createStyles } from '@/ui/theme'
import { type } from '@/ui/tokens'

import { SignalCard } from './SignalCard'

interface SignalsSectionProps {
    signals: ReportSignalView[]
    reportId: string
}

export function SignalsSection({ signals, reportId }: SignalsSectionProps): ReactElement | null {
    const styles = useStyles()
    const now = useNow()
    if (signals.length === 0) {
        return null
    }
    return (
        <View style={styles.section}>
            <View style={styles.header} accessible accessibilityRole="header">
                <Text style={styles.title}>Signals</Text>
                <Text style={styles.count}>{groupThousands(signals.length)}</Text>
            </View>
            <View style={styles.list}>
                {signals.map((signal) => (
                    <SignalCard key={signal.id} signal={signal} reportId={reportId} now={now} />
                ))}
            </View>
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    section: {
        marginTop: 12,
        paddingTop: 20,
        borderTopWidth: 1,
        borderTopColor: colors.border,
    },
    header: {
        flexDirection: 'row',
        alignItems: 'baseline',
        gap: 8,
    },
    title: {
        ...type.sectionHeader,
        color: colors.muted,
    },
    count: {
        ...type.sectionHeader,
        color: colors.tertiary,
    },
    list: {
        marginTop: 14,
        gap: 10,
    },
}))
