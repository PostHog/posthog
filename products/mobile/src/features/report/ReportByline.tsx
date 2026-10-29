import type { ReactElement } from 'react'
import { Text, View } from 'react-native'

import { sourceInfo } from '@/model/sources'
import type { ReportView } from '@/model/types'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, type } from '@/ui/tokens'

interface ReportBylineProps {
    report: Pick<ReportView, 'sourceProduct' | 'sourceLabel' | 'since'>
}

/** The source and start time under the headline, as a quiet line of facts that never change. */
export function ReportByline({ report }: ReportBylineProps): ReactElement {
    const styles = useStyles()
    const colors = useColors()
    const { Icon } = sourceInfo(report.sourceProduct)
    const since = report.since ? sinceText(report.since) : undefined
    return (
        <View
            style={styles.byline}
            accessible
            accessibilityLabel={[`From ${report.sourceLabel}`, since ? lowerFirst(since) : undefined]
                .filter(Boolean)
                .join(', ')}
            testID="report-byline"
        >
            <View style={styles.segment}>
                <View style={styles.glyph}>
                    <Icon size={iconSizes.inline} color={colors.secondary} />
                </View>
                <Text style={styles.bylineText}>{report.sourceLabel}</Text>
                {/* The separator rides on the end of the segment before it, so a wrapped line never starts with a dot. */}
                {since ? <Text style={[styles.bylineText, styles.separator]}>·</Text> : null}
            </View>
            {since ? (
                <View style={styles.segment}>
                    <Text style={styles.bylineText}>{since}</Text>
                </View>
            ) : null}
        </View>
    )
}

// Live times start with "Today" or read "Just now", which would sit oddly after "Since".
function sinceText(moment: string): string {
    if (moment === 'Just now') {
        return moment
    }
    return `Since ${moment.replace(/^Today /, 'today ')}`
}

function lowerFirst(value: string): string {
    return value.charAt(0).toLowerCase() + value.slice(1)
}

const useStyles = createStyles(({ colors }) => ({
    byline: {
        marginTop: 10,
        flexDirection: 'row',
        flexWrap: 'wrap',
        alignItems: 'center',
        rowGap: 2,
    },
    segment: {
        flexDirection: 'row',
        alignItems: 'center',
        flexShrink: 1,
    },
    bylineText: {
        ...type.meta,
        color: colors.secondary,
        flexShrink: 1,
    },
    separator: {
        color: colors.dotSeparator,
        marginHorizontal: 6,
        flexShrink: 0,
    },
    glyph: {
        marginRight: 4,
    },
}))
