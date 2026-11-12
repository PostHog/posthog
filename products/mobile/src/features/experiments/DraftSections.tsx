import { Fragment, type ReactElement, type ReactNode } from 'react'
import { Text, View } from 'react-native'

import { IconTile } from '@/ui/IconTile'
import { ArrowDownIcon } from '@/ui/icons/ArrowDownIcon'
import { ArrowUpIcon } from '@/ui/icons/ArrowUpIcon'
import { TeamsIcon } from '@/ui/icons/TeamsIcon'
import { createStyles, useColors } from '@/ui/theme'
import { fonts, radii, type } from '@/ui/tokens'

import { DetailSection, VariantSwatch } from './DetailSection'
import type { DraftVariant, MetricDef } from './detailModel'

function ListCard({ children }: { children: ReactNode[] }): ReactElement {
    const styles = useStyles()
    return (
        <View style={styles.card}>
            {children.map((child, index) => (
                // biome-ignore lint/suspicious/noArrayIndexKey: the rows are fixed for one render
                <Fragment key={index}>
                    {index > 0 ? <View style={styles.divider} /> : null}
                    {child}
                </Fragment>
            ))}
        </View>
    )
}

function Row({
    leading,
    title,
    sub,
    trailing,
    mono = false,
}: {
    leading: ReactNode
    title: string
    sub: string | null
    trailing?: ReactNode
    mono?: boolean
}): ReactElement {
    const styles = useStyles()
    return (
        <View style={styles.row} accessible accessibilityLabel={[title, sub].filter(Boolean).join(', ')}>
            {leading}
            <View style={styles.text}>
                <Text style={[styles.title, mono && styles.mono]} numberOfLines={2}>
                    {title}
                </Text>
                {sub ? (
                    <Text style={styles.sub} numberOfLines={2}>
                        {sub}
                    </Text>
                ) : null}
            </View>
            {trailing}
        </View>
    )
}

/** What a draft measures, its variants and who joins at launch, read-only. Editing stays on the web. */
export function DraftSections({
    primary,
    secondary,
    variants,
    audience,
}: {
    primary: readonly MetricDef[]
    secondary: readonly MetricDef[]
    variants: readonly DraftVariant[]
    audience: string
}): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const metrics = [...primary, ...secondary]
    const metricRow = (metric: MetricDef): ReactElement => (
        <Row
            leading={
                <IconTile muted>
                    {metric.goal === 'decrease' ? (
                        <ArrowDownIcon size={16} color={colors.ink} />
                    ) : (
                        <ArrowUpIcon size={16} color={colors.ink} />
                    )}
                </IconTile>
            }
            title={metric.name}
            sub={`${metric.role === 'primary' ? 'Primary' : 'Secondary'} · ${metric.goal === 'decrease' ? 'lower' : 'higher'} is better`}
        />
    )
    return (
        <>
            <DetailSection title="What it measures">
                {metrics.length ? (
                    <ListCard>{metrics.map(metricRow)}</ListCard>
                ) : (
                    <View style={styles.card}>
                        <Text style={styles.empty}>No metrics yet. Add them on the web before you launch.</Text>
                    </View>
                )}
            </DetailSection>
            {variants.length ? (
                <DetailSection title="Variants">
                    <ListCard>
                        {variants.map((variant) => (
                            <Row
                                key={variant.key}
                                leading={<VariantSwatch colorIndex={variant.colorIndex} />}
                                title={variant.key}
                                mono
                                sub={variant.note}
                                trailing={
                                    variant.percent === null ? undefined : (
                                        <Text style={styles.percent}>{Math.round(variant.percent)}%</Text>
                                    )
                                }
                            />
                        ))}
                    </ListCard>
                </DetailSection>
            ) : null}
            <DetailSection title="Audience">
                <ListCard>
                    {[
                        <Row
                            key="audience"
                            leading={
                                <IconTile muted>
                                    <TeamsIcon size={17} color={colors.ink} />
                                </IconTile>
                            }
                            title={audience}
                            sub="They join when it launches"
                        />,
                    ]}
                </ListCard>
            </DetailSection>
        </>
    )
}

const useStyles = createStyles(({ colors }) => ({
    card: {
        borderRadius: radii.card,
        borderWidth: 1,
        borderColor: colors.hairline,
        backgroundColor: colors.surface,
        overflow: 'hidden',
    },
    divider: {
        height: 1,
        backgroundColor: colors.hairline,
    },
    row: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
        paddingHorizontal: 14,
        paddingVertical: 12,
        minHeight: 56,
    },
    text: {
        flex: 1,
        minWidth: 0,
        gap: 2,
    },
    title: {
        ...type.bodySmallStrong,
        color: colors.ink,
    },
    mono: {
        fontFamily: fonts.mono,
        fontSize: 14,
        fontWeight: '500',
    },
    sub: {
        ...type.meta,
        color: colors.secondary,
    },
    percent: {
        ...type.metaSmall,
        fontWeight: '600',
        color: colors.secondary,
    },
    empty: {
        ...type.metaSmall,
        color: colors.secondary,
        padding: 14,
    },
}))
