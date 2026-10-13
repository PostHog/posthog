import type { ReactElement } from 'react'
import { ScrollView, StyleSheet, Text, View } from 'react-native'

import type { ChatAgentMode } from '@/api/conversations'
import { CheckIcon } from '@/ui/icons/CheckIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { colors, radii, shadows, type } from '@/ui/tokens'

import { AGENT_MODE_OPTIONS, agentModeKey } from './agentModes'

/** About five rows, so the list scrolls instead of covering the whole thread. */
const MAX_HEIGHT = 340
/** Keeps the eyebrow, Auto and part of the next row in view, so the list still reads as one that scrolls. */
const MIN_HEIGHT = 160
/** The popover's own `marginBottom` plus the same gap under the sheet header. */
const GAPS = 16

interface ModeSpace {
    sheetHeight: number
    headerHeight: number
    composerHeight: number
    /** The keyboard height, or the home indicator inset when the keyboard is down. */
    bottomInset: number
}

/** The composer autofocuses and the keyboard stays up, so the fixed cap alone runs off the top of a small phone. */
export function modePopoverMaxHeight({ sheetHeight, headerHeight, composerHeight, bottomInset }: ModeSpace): number {
    if (sheetHeight === 0) {
        return MAX_HEIGHT
    }
    const space = sheetHeight - headerHeight - composerHeight - bottomInset - GAPS
    return Math.min(MAX_HEIGHT, Math.max(MIN_HEIGHT, space))
}

interface ModePopoverProps {
    selected: ChatAgentMode | null
    onPick: (mode: ChatAgentMode | null) => void
    maxHeight: number
}

/** Anchored above the composer like `MentionPopover`, because a root-level overlay cannot reach the native modal on Android. */
export function ModePopover({ selected, onPick, maxHeight }: ModePopoverProps): ReactElement {
    return (
        <View style={[styles.popover, shadows.popover, { maxHeight }]} testID="mode-popover">
            <ScrollView keyboardShouldPersistTaps="handled">
                <Text style={[type.eyebrow, styles.eyebrow]}>MODE</Text>
                {AGENT_MODE_OPTIONS.map((option) => {
                    const isSelected = option.value === selected
                    return (
                        <Pressable44
                            key={agentModeKey(option.value)}
                            onPress={() => onPick(option.value)}
                            pressedBackground={colors.background}
                            accessibilityRole="menuitem"
                            accessibilityState={{ selected: isSelected }}
                            accessibilityLabel={`${option.label}. ${option.description}`}
                            style={[styles.row, isSelected && styles.rowSelected]}
                            testID={`chat-mode-${agentModeKey(option.value)}`}
                        >
                            <View style={styles.text}>
                                <Text style={styles.label} numberOfLines={1}>
                                    {option.label}
                                </Text>
                                <Text style={styles.description}>{option.description}</Text>
                            </View>
                            {isSelected ? (
                                <CheckIcon size={16} color={colors.ink} />
                            ) : (
                                <View style={styles.checkSpace} />
                            )}
                        </Pressable44>
                    )
                })}
            </ScrollView>
        </View>
    )
}

const styles = StyleSheet.create({
    popover: {
        position: 'absolute',
        left: 10,
        right: 10,
        bottom: '100%',
        marginBottom: 8,
        zIndex: 5,
        borderWidth: 1,
        borderColor: colors.hairline,
        borderRadius: radii.menuRow,
        backgroundColor: colors.white,
        padding: 6,
    },
    eyebrow: {
        color: colors.tertiary,
        paddingTop: 8,
        paddingHorizontal: 12,
        paddingBottom: 6,
    },
    row: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 10,
        minHeight: 56,
        paddingVertical: 8,
        paddingHorizontal: 12,
        borderRadius: radii.card,
    },
    rowSelected: {
        backgroundColor: colors.sunken,
    },
    text: {
        flex: 1,
        minWidth: 0,
        gap: 2,
    },
    label: {
        fontSize: 15,
        lineHeight: 21,
        fontWeight: '500',
        color: colors.ink,
    },
    description: {
        fontSize: 13,
        lineHeight: 18,
        color: colors.secondary,
    },
    checkSpace: {
        width: 16,
    },
})
