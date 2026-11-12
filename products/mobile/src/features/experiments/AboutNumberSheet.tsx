import { Fragment, type ReactElement, useMemo } from 'react'
import { ScrollView, Text, View } from 'react-native'
import { Gesture, GestureDetector } from 'react-native-gesture-handler'

import { BottomSheet } from '@/ui/BottomSheet'
import { createStyles } from '@/ui/theme'
import { fonts, radii, type } from '@/ui/tokens'
import { useSceneDimensions } from '@/ui/useSceneDimensions'

import type { AboutCopy } from './aboutCopy'
import { VariantSwatch } from './DetailSection'
import { IntervalBar } from './IntervalBar'

interface AboutNumberSheetProps {
    visible: boolean
    /** Kept while the sheet slides away, so its text does not vanish mid-animation. */
    copy: AboutCopy | null
    onClose: () => void
}

/** "About this number": the tapped number as the title, one plain sentence, the interval, and the exact values. */
export function AboutNumberSheet({ visible, copy, onClose }: AboutNumberSheetProps): ReactElement {
    const styles = useStyles()
    const { height } = useSceneDimensions()
    const scrollGesture = useMemo(() => Gesture.Native(), [])
    return (
        <BottomSheet
            visible={visible && copy !== null}
            onClose={onClose}
            paddingHorizontal={20}
            scrollGesture={scrollGesture}
            accessibilityLabel="About this number"
            testID="experiment-about-sheet"
        >
            {copy ? (
                <GestureDetector gesture={scrollGesture}>
                    <ScrollView
                        style={{ maxHeight: Math.round(height * 0.78) }}
                        contentContainerStyle={styles.body}
                        showsVerticalScrollIndicator={false}
                    >
                        <AboutBody copy={copy} />
                    </ScrollView>
                </GestureDetector>
            ) : null}
        </BottomSheet>
    )
}

function AboutBody({ copy }: { copy: AboutCopy }): ReactElement {
    const styles = useStyles()
    const { kicker } = copy
    return (
        <>
            <View style={styles.kicker} testID="experiment-about-kicker">
                {kicker.variantKey ? (
                    <View style={styles.variant}>
                        <View style={styles.swatch}>
                            <VariantSwatch colorIndex={kicker.colorIndex} size={9} />
                        </View>
                        <Text style={styles.variantLine}>
                            <Text style={styles.mono}>{kicker.variantKey}</Text>
                            {kicker.versus ? (
                                <>
                                    <Text style={styles.kickerText}> vs </Text>
                                    <Text style={styles.mono}>{kicker.versus}</Text>
                                </>
                            ) : null}
                        </Text>
                    </View>
                ) : (
                    <Text style={styles.kickerText}>Progress</Text>
                )}
                <Text style={styles.kickerText} numberOfLines={1}>
                    {kicker.context}
                </Text>
            </View>
            <Text
                style={[styles.title, copy.tone === 'good' && styles.good, copy.tone === 'bad' && styles.bad]}
                accessibilityRole="header"
                testID="experiment-about-title"
            >
                {copy.title}
            </Text>
            <Text style={styles.lead} testID="experiment-about-lead">
                {copy.lead}
            </Text>
            {copy.figure ? (
                <View style={styles.figure}>
                    <Text style={styles.caption}>{copy.figure.caption}</Text>
                    <IntervalBar
                        interval={copy.figure.interval}
                        delta={copy.figure.delta}
                        scale={copy.figure.scale}
                        side={copy.figure.side}
                        size="large"
                    />
                </View>
            ) : null}
            <View style={styles.rows}>
                {copy.rows.map((row, index) => (
                    <Fragment key={row.label}>
                        {index > 0 ? <View style={styles.divider} /> : null}
                        <View
                            style={styles.row}
                            accessible
                            accessibilityLabel={[row.label, row.value, row.sub].filter(Boolean).join(', ')}
                        >
                            <Text style={styles.rowLabel}>{row.label}</Text>
                            <View style={styles.rowValue}>
                                <Text style={styles.rowValueText}>{row.value}</Text>
                                {row.sub ? <Text style={styles.rowSub}>{row.sub}</Text> : null}
                            </View>
                        </View>
                    </Fragment>
                ))}
            </View>
            <View style={styles.foot}>
                <Text style={styles.footText}>{copy.foot}</Text>
            </View>
            {copy.runLine ? <Text style={styles.run}>{copy.runLine}</Text> : null}
        </>
    )
}

const useStyles = createStyles(({ colors }) => ({
    body: {
        paddingTop: 14,
        paddingBottom: 4,
    },
    kicker: {
        gap: 2,
    },
    variant: {
        flexDirection: 'row',
        alignItems: 'flex-start',
        gap: 6,
    },
    // Centers the swatch on the first line of a key that wraps.
    swatch: {
        height: 18,
        justifyContent: 'center',
    },
    variantLine: {
        flexShrink: 1,
        fontSize: 13,
        lineHeight: 18,
    },
    mono: {
        fontFamily: fonts.mono,
        fontSize: 13,
        color: colors.ink,
    },
    kickerText: {
        ...type.meta,
        color: colors.secondary,
    },
    title: {
        ...type.screenTitle,
        color: colors.ink,
        marginTop: 8,
    },
    good: {
        color: colors.diffGreen,
    },
    bad: {
        color: colors.diffRed,
    },
    lead: {
        ...type.body,
        color: colors.ink,
        marginTop: 8,
    },
    figure: {
        marginTop: 16,
        paddingTop: 14,
        paddingBottom: 12,
        borderRadius: radii.card,
        backgroundColor: colors.sunken,
        gap: 10,
    },
    caption: {
        ...type.eyebrow,
        textTransform: 'uppercase',
        color: colors.tertiary,
        paddingHorizontal: 14,
    },
    rows: {
        marginTop: 16,
        borderTopWidth: 1,
        borderTopColor: colors.hairline,
    },
    row: {
        flexDirection: 'row',
        justifyContent: 'space-between',
        gap: 12,
        paddingVertical: 12,
    },
    rowLabel: {
        ...type.bodySmall,
        color: colors.secondary,
        flexShrink: 1,
    },
    rowValue: {
        alignItems: 'flex-end',
        flexShrink: 1,
    },
    rowValueText: {
        ...type.bodySmallStrong,
        color: colors.ink,
        textAlign: 'right',
    },
    rowSub: {
        ...type.meta,
        color: colors.secondary,
        textAlign: 'right',
    },
    divider: {
        height: 1,
        backgroundColor: colors.hairline,
    },
    foot: {
        marginTop: 12,
        padding: 14,
        borderRadius: radii.card,
        backgroundColor: colors.sunken,
    },
    footText: {
        ...type.metaSmall,
        color: colors.muted,
    },
    run: {
        ...type.meta,
        color: colors.tertiary,
        marginTop: 12,
    },
}))
