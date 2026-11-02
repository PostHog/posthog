import { type ReactElement, type ReactNode, useEffect, useMemo, useRef, useState } from 'react'
import { Linking, ScrollView, Text, useWindowDimensions, View } from 'react-native'
import { Gesture, GestureDetector } from 'react-native-gesture-handler'
import { safeHttpsUrl } from '@/lib/urls'
import { useNow } from '@/lib/useNow'
import { BottomSheet } from '@/ui/BottomSheet'
import { ExternalLinkIcon } from '@/ui/icons/ExternalLinkIcon'
import { RefreshIcon } from '@/ui/icons/RefreshIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors, useTheme } from '@/ui/theme'
import { fonts, radii, type } from '@/ui/tokens'

import { trackViewOpenedInWeb } from '../analytics'
import { forceAllowedAt, HINT_MS, refreshHintText } from '../freshness'
import { type ChartSheetSource, useLiveSnapshot } from '../pointSheet/chartSheetSource'
import { SheetTitle } from '../screen/SheetTitle'
import { useViewsContext } from '../useViewsContext'
import { useItemUpdating } from '../viewsCache'
import { viewWebUrl } from '../webLinks'
import { type AboutContent, type AboutRow, aboutContent } from './aboutContent'

interface AboutSheetProps {
    /** Null closes the sheet. */
    source: ChartSheetSource | null
    onClose: () => void
}

/** "About this chart": what it counts, for which range, and how fresh it is. */
export function AboutSheet({ source, onClose }: AboutSheetProps): ReactElement {
    const colors = useColors()
    // The last source stays rendered while the sheet slides out.
    const shown = useRef<ChartSheetSource | null>(source)
    if (source) {
        shown.current = source
    }
    const current = shown.current
    const listGesture = useMemo(() => Gesture.Native(), [])
    return (
        <BottomSheet
            visible={source !== null}
            onClose={onClose}
            scrollGesture={listGesture}
            backgroundColor={colors.background}
            accessibilityLabel="About this chart"
            testID="about-sheet"
        >
            {current ? <AboutBody source={current} listGesture={listGesture} onClose={onClose} /> : null}
        </BottomSheet>
    )
}

function AboutBody({
    source,
    listGesture,
    onClose,
}: {
    source: ChartSheetSource
    listGesture: ReturnType<typeof Gesture.Native>
    onClose: () => void
}): ReactElement | null {
    const { colors, chartPalette } = useTheme()
    const styles = useStyles()
    const snapshot = useLiveSnapshot(source)
    const now = useNow(30_000)
    const { height } = useWindowDimensions()
    const { scope } = useViewsContext()
    const updating = useItemUpdating(source.itemKey)
    const [hint, setHint] = useState<string | null>(null)
    useEffect(() => {
        if (!hint) {
            return undefined
        }
        const timer = setTimeout(() => setHint(null), HINT_MS)
        return () => clearTimeout(timer)
    }, [hint])

    if (!snapshot) {
        return null
    }
    const content = aboutContent(snapshot, now.getTime(), chartPalette)
    const webUrl = viewWebUrl(scope, `/insights/${snapshot.shortId}`)
    const { itemKey, refreshItem } = source

    const refresh = (): void => {
        if (!itemKey || !refreshItem) {
            return
        }
        if (!refreshItem(itemKey)) {
            setHint(refreshHintText(forceAllowedAt(snapshot)))
        }
    }
    const openWeb = (): void => {
        const safe = webUrl ? safeHttpsUrl(webUrl) : undefined
        if (!safe) {
            return
        }
        trackViewOpenedInWeb({ viewType: 'insight', reason: 'action' })
        Linking.openURL(safe).catch(() => undefined)
    }

    return (
        <View>
            <SheetTitle title="About this chart" subtitle={content.name} onDone={onClose} />
            <GestureDetector gesture={listGesture}>
                <ScrollView style={{ maxHeight: Math.round(height * 0.74) }} contentContainerStyle={styles.body}>
                    {content.description ? (
                        <Section title="Description">
                            <Text style={styles.paragraph}>{content.description}</Text>
                        </Section>
                    ) : null}
                    <Measures content={content} />
                    <Section title="Breakdown and filters">
                        <KeyValues
                            rows={[
                                { label: 'Breakdown', values: [content.breakdown], mono: false },
                                {
                                    label: 'Filters',
                                    values: content.filters.length > 0 ? content.filters : ['None'],
                                    mono: content.filters.length > 0,
                                },
                                { label: 'Test users', values: [content.testAccounts], mono: false },
                            ]}
                        />
                    </Section>
                    <Section title="Time">
                        <KeyValues
                            rows={[
                                { label: 'Date range', values: [content.range], mono: false },
                                ...(content.interval
                                    ? [{ label: 'Interval', values: [content.interval], mono: false }]
                                    : []),
                                { label: 'Compare', values: [content.compare], mono: false },
                            ]}
                        />
                    </Section>
                    <Section title="Freshness">
                        <KeyValues
                            rows={[
                                {
                                    label: 'Computed',
                                    values: [updating ? 'Updating…' : (content.computed ?? 'Not yet')],
                                    mono: false,
                                },
                            ]}
                        />
                        {content.inProgressNote ? <Text style={styles.note}>{content.inProgressNote}</Text> : null}
                        {itemKey && refreshItem ? (
                            <View style={styles.chips}>
                                <ChipButton
                                    label="Refresh"
                                    icon={<RefreshIcon size={16} />}
                                    onPress={refresh}
                                    disabled={updating}
                                    testID="about-refresh"
                                />
                            </View>
                        ) : null}
                        {hint ? (
                            <Text style={styles.hint} accessibilityLiveRegion="polite">
                                {hint}
                            </Text>
                        ) : null}
                    </Section>
                    <Section title="Source">
                        <KeyValues
                            rows={[
                                { label: 'Insight', values: [content.name], mono: false },
                                ...(source.dashboardName
                                    ? [{ label: 'Dashboard', values: [source.dashboardName], mono: false }]
                                    : []),
                                ...(content.createdBy
                                    ? [{ label: 'Created by', values: [content.createdBy], mono: false }]
                                    : []),
                            ]}
                        />
                        <View style={styles.chips}>
                            <ChipButton
                                label={webUrl ? 'Open on web' : 'Not available in the demo'}
                                icon={<ExternalLinkIcon size={16} color={webUrl ? colors.ink : colors.disabled} />}
                                onPress={openWeb}
                                disabled={!webUrl}
                                testID="about-open-web"
                            />
                        </View>
                    </Section>
                </ScrollView>
            </GestureDetector>
        </View>
    )
}

function Measures({ content }: { content: AboutContent }): ReactElement {
    const styles = useStyles()
    return (
        <Section title="What it measures">
            {content.series.map((series) => (
                <View key={series.key} style={styles.series}>
                    <View style={styles.seriesHead}>
                        <View style={[styles.swatch, { backgroundColor: series.color }]} />
                        <Text style={styles.seriesName}>{series.label}</Text>
                    </View>
                    <KeyValues rows={series.rows} />
                </View>
            ))}
            {content.formula ? (
                <KeyValues rows={[{ label: 'Formula', values: [content.formula], mono: true }]} />
            ) : null}
            {content.sql ? (
                <Text style={styles.sql} numberOfLines={12}>
                    {content.sql}
                </Text>
            ) : null}
            {content.sqlResult ? (
                <KeyValues rows={[{ label: 'Result', values: [content.sqlResult], mono: false }]} />
            ) : null}
            {content.series.length === 0 && !content.sql ? (
                <Text style={styles.paragraph}>Open it on the web to see how this chart is built.</Text>
            ) : null}
        </Section>
    )
}

function Section({ title, children }: { title: string; children: ReactNode }): ReactElement {
    const styles = useStyles()
    return (
        <View style={styles.section}>
            <Text style={styles.sectionTitle} accessibilityRole="header">
                {title}
            </Text>
            {children}
        </View>
    )
}

function KeyValues({ rows }: { rows: AboutRow[] }): ReactElement {
    const styles = useStyles()
    return (
        <View style={styles.rows}>
            {rows.map((row) => (
                <View key={row.label} style={styles.row}>
                    <Text style={styles.key}>{row.label}</Text>
                    <View style={styles.values}>
                        {row.values.map((value) =>
                            row.mono ? (
                                <Text key={value} style={styles.chip}>
                                    {value}
                                </Text>
                            ) : (
                                <Text key={value} style={styles.value}>
                                    {value}
                                </Text>
                            )
                        )}
                    </View>
                </View>
            ))}
        </View>
    )
}

function ChipButton({
    label,
    icon,
    onPress,
    disabled = false,
    testID,
}: {
    label: string
    icon: ReactNode
    onPress: () => void
    disabled?: boolean
    testID?: string
}): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    return (
        <Pressable44
            onPress={onPress}
            disabled={disabled}
            style={styles.chipButton}
            pressedBackground={colors.pressed}
            testID={testID}
        >
            {icon}
            <Text style={[styles.chipLabel, disabled && styles.disabled]}>{label}</Text>
        </Pressable44>
    )
}

const useStyles = createStyles(({ colors }) => ({
    body: {
        gap: 14,
        paddingBottom: 8,
    },
    section: {
        gap: 8,
        padding: 14,
        borderRadius: radii.option,
        borderWidth: 1,
        borderColor: colors.hairline,
        backgroundColor: colors.surface,
    },
    sectionTitle: {
        ...type.eyebrow,
        color: colors.tertiary,
        textTransform: 'uppercase',
    },
    paragraph: {
        ...type.bodySmall,
        color: colors.ink,
    },
    series: {
        gap: 6,
    },
    seriesHead: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
    },
    swatch: {
        width: 10,
        height: 10,
        borderRadius: 3,
    },
    seriesName: {
        ...type.bodyStrong,
        color: colors.ink,
        flexShrink: 1,
    },
    rows: {
        gap: 6,
    },
    row: {
        flexDirection: 'row',
        gap: 12,
    },
    key: {
        width: 96,
        fontSize: 14,
        lineHeight: 20,
        color: colors.tertiary,
    },
    values: {
        flex: 1,
        minWidth: 0,
        flexDirection: 'row',
        flexWrap: 'wrap',
        gap: 4,
    },
    value: {
        fontSize: 14,
        lineHeight: 20,
        color: colors.ink,
        flexShrink: 1,
    },
    chip: {
        fontFamily: fonts.mono,
        fontSize: 12,
        lineHeight: 18,
        color: colors.ink,
        paddingHorizontal: 8,
        paddingVertical: 3,
        borderRadius: radii.markSmall,
        backgroundColor: colors.sunken,
        overflow: 'hidden',
    },
    sql: {
        fontFamily: fonts.mono,
        fontSize: 12,
        lineHeight: 18,
        color: colors.ink,
        padding: 10,
        borderRadius: radii.tile,
        backgroundColor: colors.sunken,
        overflow: 'hidden',
    },
    note: {
        ...type.metaSmall,
        lineHeight: 20,
        color: colors.tertiary,
    },
    chips: {
        flexDirection: 'row',
        flexWrap: 'wrap',
        gap: 8,
        marginTop: 2,
    },
    chipButton: {
        height: 36,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
        paddingLeft: 12,
        paddingRight: 14,
        borderRadius: radii.pill,
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: colors.surface,
    },
    chipLabel: {
        fontSize: 14,
        fontWeight: '600',
        color: colors.ink,
    },
    disabled: {
        color: colors.disabled,
    },
    hint: {
        fontSize: 13,
        lineHeight: 16,
        fontWeight: '600',
        color: colors.muted,
    },
}))
