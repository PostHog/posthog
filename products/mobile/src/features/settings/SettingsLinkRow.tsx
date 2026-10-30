import type { ReactElement } from 'react'
import { Text } from 'react-native'

import { ExternalLinkIcon } from '@/ui/icons/ExternalLinkIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, type } from '@/ui/tokens'

interface SettingsLinkRowProps {
    label: string
    onPress: () => void
    testID?: string
}

/** A Settings row that opens a web page in the browser. */
export function SettingsLinkRow({ label, onPress, testID }: SettingsLinkRowProps): ReactElement {
    const styles = useStyles()
    const colors = useColors()
    return (
        <Pressable44
            onPress={onPress}
            accessibilityRole="link"
            accessibilityHint="Opens in your browser"
            pressedBackground={colors.background}
            style={styles.row}
            testID={testID}
        >
            <Text style={styles.label}>{label}</Text>
            <ExternalLinkIcon size={iconSizes.inline} color={colors.tertiary} />
        </Pressable44>
    )
}

const useStyles = createStyles(({ colors }) => ({
    row: {
        minHeight: 52,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
        paddingHorizontal: 16,
    },
    label: {
        ...type.body,
        color: colors.ink,
        flex: 1,
    },
}))
