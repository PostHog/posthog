import { type ReactElement, useEffect, useState } from 'react'
import { ActivityIndicator, Text, View } from 'react-native'

import { actionErrorMessage } from '@/lib/errors'
import type { ReportPriority } from '@/model/types'
import { BottomSheet } from '@/ui/BottomSheet'
import { Dot } from '@/ui/Dot'
import { CheckIcon } from '@/ui/icons/CheckIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, type ThemeColors, useColors } from '@/ui/theme'
import { iconSizes, radii, type } from '@/ui/tokens'

export const PRIORITIES: readonly ReportPriority[] = ['P0', 'P1', 'P2', 'P3', 'P4']

export interface PriorityTone {
    dot: string
    text: string
}

// Only the two urgent levels color their text, so P2 and below stay quiet next to the owner chip.
export function priorityTone(priority: ReportPriority | undefined, colors: ThemeColors): PriorityTone {
    switch (priority) {
        case 'P0':
        case 'P1':
            return { dot: colors.orange, text: colors.orange }
        case 'P2':
            return { dot: colors.yellow, text: colors.ink }
        case 'P3':
        case 'P4':
            return { dot: colors.tertiary, text: colors.ink }
        default:
            return { dot: colors.tertiary, text: colors.muted }
    }
}

export interface PrioritySheetProps {
    visible: boolean
    current?: ReportPriority
    onClose: () => void
    /** A rejection keeps the sheet open with the error under the title. */
    onSelect: (priority: ReportPriority) => Promise<void>
    pending: boolean
}

interface RowProps {
    priority: ReportPriority
    selected: boolean
    busy: boolean
    disabled: boolean
    onPress: () => void
}

function PriorityRow({ priority, selected, busy, disabled, onPress }: RowProps): ReactElement {
    const styles = useStyles()
    const colors = useColors()
    const tone = priorityTone(priority, colors)
    return (
        <Pressable44
            onPress={onPress}
            disabled={disabled}
            accessibilityRole="radio"
            accessibilityLabel={priority}
            accessibilityState={{ checked: selected, disabled, busy }}
            pressedBackground={colors.background}
            style={styles.row}
            testID={`priority-${priority}`}
        >
            <View style={styles.dot}>
                <Dot color={tone.dot} size={10} />
            </View>
            <Text style={[styles.code, { color: tone.text }]}>{priority}</Text>
            {busy ? (
                <ActivityIndicator size="small" color={colors.ink} />
            ) : selected ? (
                <CheckIcon size={iconSizes.control} />
            ) : null}
        </Pressable44>
    )
}

export function PrioritySheet({ visible, current, onClose, onSelect, pending }: PrioritySheetProps): ReactElement {
    const styles = useStyles()
    const [picked, setPicked] = useState<ReportPriority | undefined>(undefined)
    const [error, setError] = useState<string | undefined>(undefined)

    useEffect(() => {
        if (visible) {
            setPicked(undefined)
            setError(undefined)
        }
    }, [visible])

    const pick = (priority: ReportPriority): void => {
        setPicked(priority)
        setError(undefined)
        onSelect(priority).catch((selectError: unknown) => setError(actionErrorMessage(selectError)))
    }

    return (
        <BottomSheet
            visible={visible}
            onClose={onClose}
            paddingHorizontal={20}
            accessibilityLabel="Priority"
            testID="priority-sheet"
        >
            <Text style={styles.title}>Priority</Text>
            {error ? (
                <Text style={styles.error} accessibilityRole="alert" testID="priority-error">
                    {error}
                </Text>
            ) : null}
            <View style={styles.rows} accessibilityRole="radiogroup">
                {PRIORITIES.map((priority) => (
                    <PriorityRow
                        key={priority}
                        priority={priority}
                        selected={priority === current}
                        busy={pending && priority === picked}
                        disabled={pending}
                        onPress={() => pick(priority)}
                    />
                ))}
            </View>
        </BottomSheet>
    )
}

const useStyles = createStyles(({ colors }) => ({
    title: {
        ...type.sheetTitle,
        color: colors.ink,
        marginTop: 18,
        paddingHorizontal: 4,
    },
    error: {
        ...type.metaSmall,
        color: colors.orange,
        marginTop: 6,
        paddingHorizontal: 4,
    },
    rows: {
        marginTop: 8,
    },
    row: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 14,
        minHeight: 56,
        paddingHorizontal: 4,
        borderRadius: radii.card,
    },
    // Matches the 20pt icon column of the other option sheets so the codes line up with their labels.
    dot: {
        width: iconSizes.control,
        alignItems: 'center',
    },
    code: {
        ...type.label,
        fontWeight: '600',
        flex: 1,
    },
}))
