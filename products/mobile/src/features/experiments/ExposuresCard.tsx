import { Fragment, type ReactElement } from 'react'
import { Text, View } from 'react-native'

import { ErrorTriangleIcon } from '@/ui/icons/ErrorTriangleIcon'
import { createStyles, useColors } from '@/ui/theme'
import { fonts, radii, type } from '@/ui/tokens'

import { useVariantColor, VariantSwatch } from './DetailSection'
import { type ExposureModel, formatCount, sampleRatioText } from './detailModel'

/**
 * People per variant with a share bar. These count people who saw the flag; metric counts can differ. The sample ratio
 * warning shows only when the split test fails.
 */
export function ExposuresCard({ model }: { model: ExposureModel }): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const colorOf = useVariantColor()
    const srm = model.srm ? sampleRatioText(model.srm) : null
    const anyExposures = model.rows.some((row) => row.count > 0)
    return (
        <View style={styles.card} testID="experiment-exposures">
            {srm ? (
                <View
                    style={styles.warning}
                    accessible
                    accessibilityRole="alert"
                    accessibilityLabel={`${srm.strong} ${srm.text}`}
                    testID="experiment-srm"
                >
                    <ErrorTriangleIcon size={18} color={colors.orange} strokeWidth={2.2} />
                    <Text style={styles.warningText}>
                        <Text style={styles.strong}>{srm.strong}</Text> {srm.text}
                    </Text>
                </View>
            ) : null}
            <View style={styles.bar} importantForAccessibility="no-hide-descendants" accessibilityElementsHidden>
                {model.rows.map((row) => (
                    <View
                        key={row.key}
                        style={{
                            flex: anyExposures ? Math.max(row.count, 0.0001) : 1,
                            backgroundColor: colorOf(row.colorIndex),
                            opacity: anyExposures ? 1 : 0.25,
                        }}
                    />
                ))}
            </View>
            {model.rows.map((row, index) => (
                <Fragment key={row.key}>
                    {index > 0 ? <View style={styles.divider} /> : null}
                    <View
                        style={styles.row}
                        accessible
                        accessibilityLabel={`${row.key}: ${formatCount(row.count)} people, ${(row.share * 100).toFixed(1)}%`}
                    >
                        <View style={styles.key}>
                            <VariantSwatch colorIndex={row.colorIndex} />
                            <Text style={styles.keyText} numberOfLines={1}>
                                {row.key}
                            </Text>
                        </View>
                        <Text style={styles.count}>{formatCount(row.count)}</Text>
                        <Text style={styles.share}>{(row.share * 100).toFixed(1)}%</Text>
                    </View>
                </Fragment>
            ))}
            {model.multiple > 0 ? (
                <Text style={styles.note}>
                    {formatCount(model.multiple)} {model.multiple === 1 ? 'person' : 'people'} saw more than one
                    variant. The results leave them out.
                </Text>
            ) : null}
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    card: {
        paddingHorizontal: 14,
        paddingTop: 14,
        paddingBottom: 6,
        borderRadius: radii.card,
        borderWidth: 1,
        borderColor: colors.hairline,
        backgroundColor: colors.surface,
    },
    warning: {
        flexDirection: 'row',
        alignItems: 'flex-start',
        gap: 10,
        padding: 12,
        marginBottom: 12,
        borderRadius: 10,
        borderWidth: 1,
        borderColor: colors.orangeLight,
        backgroundColor: colors.sunken,
    },
    warningText: {
        ...type.metaSmall,
        color: colors.ink,
        flex: 1,
    },
    strong: {
        fontWeight: '700',
    },
    bar: {
        flexDirection: 'row',
        height: 8,
        gap: 3,
        borderRadius: 4,
        overflow: 'hidden',
        marginBottom: 6,
    },
    row: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 10,
        minHeight: 44,
    },
    key: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
        flex: 1,
        minWidth: 0,
    },
    keyText: {
        fontFamily: fonts.mono,
        fontSize: 14,
        color: colors.ink,
        flexShrink: 1,
    },
    count: {
        fontFamily: fonts.mono,
        fontSize: 15,
        fontWeight: '600',
        color: colors.ink,
    },
    share: {
        ...type.metaSmall,
        color: colors.secondary,
        width: 56,
        textAlign: 'right',
    },
    divider: {
        height: 1,
        backgroundColor: colors.hairline,
    },
    note: {
        ...type.meta,
        color: colors.secondary,
        paddingTop: 4,
        paddingBottom: 8,
    },
}))
