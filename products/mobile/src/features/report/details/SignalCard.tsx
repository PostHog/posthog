import type { ReactElement } from 'react'
import { Text, View } from 'react-native'

import { formatActivityTime } from '@/lib/dates'
import { sourceInfo } from '@/model/sources'
import type { ReportSignalView } from '@/model/types'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, radii, type } from '@/ui/tokens'

import { TextLinkRow } from '../TextLinkRow'
import { openDetailsLink } from './openDetailsLink'
import { ReportMarkdown } from './ReportMarkdown'

interface SignalCardProps {
    signal: ReportSignalView
    reportId: string
    now: Date
}

export function SignalCard({ signal, reportId, now }: SignalCardProps): ReactElement {
    const styles = useStyles()
    const colors = useColors()
    const { Icon } = sourceInfo(signal.sourceProduct)
    const meta = [
        signal.sourceLabel,
        formatActivityTime(signal.at, now),
        signal.ticketNumber !== undefined ? `Ticket #${signal.ticketNumber}` : undefined,
    ]
        .filter(Boolean)
        .join(' · ')
    const { replayUrl } = signal
    return (
        <View style={styles.card} testID="report-details-signal">
            <View style={styles.header} accessible accessibilityLabel={meta}>
                <Icon size={iconSizes.inline} color={colors.secondary} />
                <Text style={styles.meta} numberOfLines={1}>
                    {meta}
                </Text>
            </View>
            {signal.content ? <ReportMarkdown text={signal.content} reportId={reportId} tone="signal" /> : null}
            {replayUrl ? (
                <View style={styles.replay}>
                    <TextLinkRow
                        label="Watch session"
                        external
                        onPress={() => openDetailsLink(replayUrl, reportId, 'replay')}
                        testID="report-details-watch-session"
                    />
                </View>
            ) : null}
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    card: {
        borderWidth: 1,
        borderColor: colors.border,
        borderRadius: radii.card,
        backgroundColor: colors.surface,
        paddingTop: 12,
        paddingHorizontal: 14,
        // Every markdown block ends with a 10pt margin, so the card's bottom padding makes up the rest of 14pt.
        paddingBottom: 4,
    },
    header: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 6,
        marginBottom: 8,
    },
    meta: {
        ...type.meta,
        flexShrink: 1,
        color: colors.secondary,
    },
    replay: {
        marginTop: -4,
        marginBottom: 4,
    },
}))
