import { type ReactElement, useRef } from 'react'
import { StyleSheet, Text, View } from 'react-native'

import { BREAKDOWN_LABELS, type WebTileDef } from '@/model/adapters/webAnalyticsBreakdowns'
import type { WebBreakdown } from '@/model/views'
import { BottomSheet } from '@/ui/BottomSheet'
import { CheckIcon } from '@/ui/icons/CheckIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'

import { SheetTitle } from '../screen/SheetTitle'

interface BreakdownSheetProps {
    /** Null closes the sheet. */
    tile: WebTileDef | null
    selected: WebBreakdown | null
    onPick: (breakdown: WebBreakdown) => void
    onClose: () => void
}

export function BreakdownSheet({ tile, selected, onPick, onClose }: BreakdownSheetProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    // The last tile stays rendered while the sheet slides out.
    const shown = useRef<{ tile: WebTileDef; selected: WebBreakdown | null } | null>(null)
    if (tile) {
        shown.current = { tile, selected }
    }
    const current = shown.current
    return (
        <BottomSheet
            visible={tile !== null}
            onClose={onClose}
            backgroundColor={colors.background}
            accessibilityLabel="Break down by"
            testID="web-breakdown-sheet"
        >
            {current ? (
                <View style={styles.body}>
                    <SheetTitle title="Break down by" subtitle={current.tile.title} onDone={onClose} />
                    <View style={styles.group} accessibilityRole="radiogroup">
                        {current.tile.tabs.map((breakdown, index) => {
                            const active = breakdown === current.selected
                            return (
                                <Pressable44
                                    key={breakdown}
                                    onPress={() => {
                                        onPick(breakdown)
                                        onClose()
                                    }}
                                    hitSlop={0}
                                    accessibilityRole="radio"
                                    accessibilityState={{ selected: active }}
                                    accessibilityLabel={BREAKDOWN_LABELS[breakdown]}
                                    pressedBackground={colors.pressed}
                                    style={[styles.option, index > 0 && styles.divider]}
                                    testID={`web-breakdown-option-${breakdown}`}
                                >
                                    <Text style={[styles.optionText, active && styles.optionTextActive]}>
                                        {BREAKDOWN_LABELS[breakdown]}
                                    </Text>
                                    {active ? <CheckIcon size={16} color={colors.blue} /> : null}
                                </Pressable44>
                            )
                        })}
                    </View>
                </View>
            ) : null}
        </BottomSheet>
    )
}

const useStyles = createStyles(({ colors }) => ({
    body: {
        paddingBottom: 8,
    },
    group: {
        borderRadius: radii.option,
        borderWidth: 1,
        borderColor: colors.hairline,
        backgroundColor: colors.surface,
        overflow: 'hidden',
    },
    option: {
        minHeight: 52,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 10,
        paddingHorizontal: 16,
        backgroundColor: colors.surface,
    },
    divider: {
        borderTopWidth: StyleSheet.hairlineWidth,
        borderTopColor: colors.rowDivider,
    },
    optionText: {
        ...type.body,
        flex: 1,
        color: colors.ink,
    },
    optionTextActive: {
        fontWeight: '600',
    },
}))
