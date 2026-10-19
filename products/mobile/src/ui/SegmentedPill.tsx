import { Fragment, type ReactElement, type ReactNode } from 'react'
import { type AccessibilityRole, type StyleProp, StyleSheet, View, type ViewStyle } from 'react-native'

import { Pressable44 } from './Pressable44'
import { colors, radii, shadows } from './tokens'

export interface Segment {
    key: string
    accessibilityLabel: string
    onPress: () => void
    children: ReactNode
    selected?: boolean
    disabled?: boolean
    /** `radio` when the pill is a single choice among the segments. */
    accessibilityRole?: AccessibilityRole
    testID?: string
}

interface SegmentedPillProps {
    segments: Segment[]
    height?: number
    segmentWidth?: number
    raised?: boolean
    style?: StyleProp<ViewStyle>
}

export function SegmentedPill({
    segments,
    height = 44,
    segmentWidth,
    raised = false,
    style,
}: SegmentedPillProps): ReactElement {
    return (
        <View style={[styles.outer, { height }, raised && shadows.chip, style]}>
            <View style={styles.inner}>
                {segments.map((segment, index) => (
                    <Fragment key={segment.key}>
                        {index > 0 ? <View style={styles.divider} /> : null}
                        <Pressable44
                            accessibilityLabel={segment.accessibilityLabel}
                            accessibilityRole={segment.accessibilityRole}
                            accessibilityState={{ selected: segment.selected, disabled: segment.disabled }}
                            disabled={segment.disabled}
                            onPress={segment.onPress}
                            pressedBackground={colors.background}
                            testID={segment.testID}
                            style={[
                                styles.segment,
                                segmentWidth === undefined ? styles.flexSegment : { width: segmentWidth },
                                { height: height - 2 },
                                segment.selected && styles.selected,
                            ]}
                        >
                            {segment.children}
                        </Pressable44>
                    </Fragment>
                ))}
            </View>
        </View>
    )
}

const styles = StyleSheet.create({
    outer: {
        borderRadius: radii.pill,
        backgroundColor: colors.white,
        borderWidth: 1,
        borderColor: colors.border,
    },
    inner: {
        flex: 1,
        flexDirection: 'row',
        borderRadius: radii.pill,
        overflow: 'hidden',
    },
    segment: {
        alignItems: 'center',
        justifyContent: 'center',
    },
    flexSegment: {
        flex: 1,
    },
    selected: {
        backgroundColor: colors.sunken,
    },
    divider: {
        width: 1,
        marginVertical: 10,
        backgroundColor: colors.border,
    },
})
