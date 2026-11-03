import type { ReactElement, ReactNode } from 'react'
import { type LayoutChangeEvent, Text, View } from 'react-native'

import { Eyebrow } from '@/ui/Eyebrow'
import { RefreshHint } from '@/ui/RefreshHint'
import { createStyles } from '@/ui/theme'
import { lineHeight, prettyWrap, type } from '@/ui/tokens'

import type { ViewRefresh } from '../useViewRefresh'

interface ViewTitleProps {
    onTitleLayout?: (event: LayoutChangeEvent) => void
    /** "Insight · Line" above an insight's title. */
    eyebrow?: string
    title: string
    /** The ⓘ and pin buttons beside the title. */
    accessories?: ReactNode
    refresh: ViewRefresh
    /** The range control, or the range slot until it exists. */
    range: ReactNode
    /** The resolved dates under the range, such as "Oct 8 – 14". */
    rangeDetail?: ReactNode
}

/** The top of a view's content: title with its buttons, the status line, the refresh hint and the range. */
export function ViewTitle({
    eyebrow,
    title,
    accessories,
    refresh,
    range,
    rangeDetail,
    onTitleLayout,
}: ViewTitleProps): ReactElement {
    const styles = useStyles()
    return (
        <View style={styles.block}>
            <View onLayout={onTitleLayout}>
                {eyebrow ? (
                    <View style={styles.eyebrow}>
                        <Eyebrow>{eyebrow}</Eyebrow>
                    </View>
                ) : null}
                <View style={styles.titleRow}>
                    <Text style={styles.title} accessibilityRole="header" lineBreakStrategyIOS="standard">
                        {title}
                    </Text>
                    {accessories}
                </View>
            </View>
            <Text
                style={styles.status}
                accessibilityRole="text"
                accessibilityLiveRegion="polite"
                testID="views-updated"
            >
                {refresh.status.text ?? ''}
            </Text>
            {refresh.hint ? <RefreshHint text={refresh.hint} style={styles.hint} /> : null}
            {range}
            {rangeDetail ? (
                <View style={styles.rangeDetail}>
                    {typeof rangeDetail === 'string' ? (
                        <Text style={styles.rangeText}>{rangeDetail}</Text>
                    ) : (
                        rangeDetail
                    )}
                </View>
            ) : null}
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    block: {
        paddingHorizontal: 6,
        marginBottom: 16,
    },
    eyebrow: {
        marginBottom: 4,
    },
    titleRow: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 4,
    },
    title: {
        ...type.screenTitle,
        fontSize: 26,
        lineHeight: 34,
        color: colors.ink,
        flexShrink: 1,
        ...prettyWrap,
    },
    status: {
        ...type.meta,
        lineHeight: 18,
        minHeight: 18,
        color: colors.tertiary,
        fontVariant: ['tabular-nums'],
    },
    hint: {
        marginTop: 2,
    },
    rangeDetail: {
        marginTop: 8,
    },
    rangeText: {
        ...type.meta,
        lineHeight: lineHeight(13),
        color: colors.tertiary,
    },
}))
