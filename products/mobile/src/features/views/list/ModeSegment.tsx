import type { ReactElement } from 'react'
import { Text, View } from 'react-native'

import type { PinDisplayMode } from '@/model/views'
import { LineChartIcon } from '@/ui/icons/LineChartIcon'
import { RowsIcon } from '@/ui/icons/RowsIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useTheme } from '@/ui/theme'
import { radii } from '@/ui/tokens'

const MODES: readonly PinDisplayMode[] = ['row', 'number', 'chart']

const LABEL: Record<PinDisplayMode, string> = { row: 'Row', number: 'Number', chart: 'Chart' }

interface ModeSegmentProps {
    value: PinDisplayMode
    /** The modes this pin offers. The others show disabled. */
    available: readonly PinDisplayMode[]
    onChange: (mode: PinDisplayMode) => void
    /** `labels` for the long-press menu, `icons` for the compact toggle in Edit pins. */
    variant: 'labels' | 'icons'
    /** The view's name, for "Show Signups as". */
    name: string
    testIDFor: (mode: PinDisplayMode) => string
}

/** Row, Number or Chart for one pin. */
export function ModeSegment({ value, available, onChange, variant, name, testIDFor }: ModeSegmentProps): ReactElement {
    const { colors, shadows } = useTheme()
    const styles = useStyles()
    const icons = variant === 'icons'
    return (
        <View
            style={icons ? styles.mini : styles.full}
            accessibilityRole="radiogroup"
            accessibilityLabel={`Show ${name} as`}
        >
            {MODES.map((mode) => {
                const selected = mode === value
                const disabled = !available.includes(mode)
                const color = selected
                    ? colors.ink
                    : disabled
                      ? colors.disabled
                      : icons
                        ? colors.tertiary
                        : colors.secondary
                return (
                    <Pressable44
                        key={mode}
                        onPress={() => onChange(mode)}
                        disabled={disabled}
                        accessibilityRole="radio"
                        accessibilityLabel={LABEL[mode]}
                        accessibilityState={{ checked: selected, disabled }}
                        hitSlop={icons ? { top: 7, bottom: 7 } : 6}
                        haptic="selection"
                        style={[
                            icons ? styles.miniButton : styles.fullButton,
                            selected && styles.selected,
                            selected && shadows.chip,
                        ]}
                        testID={testIDFor(mode)}
                    >
                        {!icons ? (
                            <Text style={[styles.label, { color }]}>{LABEL[mode]}</Text>
                        ) : mode === 'row' ? (
                            <RowsIcon size={18} color={color} />
                        ) : mode === 'number' ? (
                            <Text style={[styles.numberGlyph, { color }]}>123</Text>
                        ) : (
                            <LineChartIcon size={18} color={color} strokeWidth={1.9} />
                        )}
                    </Pressable44>
                )
            })}
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    full: {
        flexDirection: 'row',
        gap: 2,
        padding: 3,
        borderRadius: radii.pill,
        backgroundColor: colors.sunken,
    },
    fullButton: {
        flex: 1,
        height: 32,
        borderRadius: radii.pill,
        alignItems: 'center',
        justifyContent: 'center',
    },
    label: {
        fontSize: 14,
        fontWeight: '600',
    },
    mini: {
        flexDirection: 'row',
        gap: 2,
        padding: 2,
        borderRadius: radii.tile,
        backgroundColor: colors.sunken,
    },
    miniButton: {
        width: 32,
        height: 30,
        borderRadius: 8,
        alignItems: 'center',
        justifyContent: 'center',
    },
    selected: {
        backgroundColor: colors.surface,
    },
    numberGlyph: {
        fontSize: 10,
        lineHeight: 13,
        fontWeight: '700',
    },
}))
