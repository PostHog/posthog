import type { ReactElement } from 'react'
import { Text, View } from 'react-native'

import type { PermissionModeApi, RuntimeAdapterApi } from '@/api/tasks'
import { CheckIcon } from '@/ui/icons/CheckIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, radii, type } from '@/ui/tokens'

import { modesForRuntimeAdapter } from './runOptions'
import { SheetPageHeader } from './SheetPageHeader'

interface ModePageProps {
    runtimeAdapter: RuntimeAdapterApi
    current: PermissionModeApi
    onPick: (mode: PermissionModeApi) => void
    onBack: () => void
}

export function ModePage({ runtimeAdapter, current, onPick, onBack }: ModePageProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    return (
        <View testID="handoff-mode-page">
            <SheetPageHeader title="Mode" onBack={onBack} testID="handoff-mode-page" />
            <View style={styles.rows} accessibilityRole="radiogroup">
                {modesForRuntimeAdapter(runtimeAdapter).map((option) => {
                    const selected = option.value === current
                    return (
                        <Pressable44
                            key={option.value}
                            onPress={() => onPick(option.value)}
                            accessibilityRole="radio"
                            accessibilityLabel={option.label}
                            accessibilityHint={option.description}
                            accessibilityState={{ checked: selected }}
                            pressedBackground={colors.background}
                            style={styles.row}
                            testID={`handoff-mode-${option.value}`}
                        >
                            <View style={styles.body}>
                                <Text style={styles.label}>{option.label}</Text>
                                <Text style={styles.description}>{option.description}</Text>
                            </View>
                            <View style={styles.check}>{selected ? <CheckIcon size={iconSizes.control} /> : null}</View>
                        </Pressable44>
                    )
                })}
            </View>
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    rows: {
        marginTop: 4,
    },
    row: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
        minHeight: 56,
        paddingVertical: 10,
        paddingHorizontal: 4,
        borderRadius: radii.card,
    },
    body: {
        flex: 1,
        minWidth: 0,
        gap: 2,
    },
    label: {
        ...type.bodyStrong,
        color: colors.ink,
    },
    description: {
        ...type.meta,
        color: colors.muted,
    },
    check: {
        width: iconSizes.control,
        alignItems: 'center',
    },
}))
