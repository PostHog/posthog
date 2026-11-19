import type { ReactElement } from 'react'
import { Text } from 'react-native'

import { ChevronRightIcon } from '@/ui/icons/ChevronRightIcon'
import { ExternalLinkIcon } from '@/ui/icons/ExternalLinkIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, lineHeight } from '@/ui/tokens'

const ROW_HEIGHT = 32

interface TextLinkRowProps {
    label: string
    onPress: () => void
    /** Opens the browser, so the trailing mark is the external-link glyph instead of a chevron. */
    external?: boolean
    testID?: string
}

/** A quiet text link with a trailing mark. 32pt tall, so the default hit slop makes the target 44pt. */
export function TextLinkRow({ label, onPress, external = false, testID }: TextLinkRowProps): ReactElement {
    const styles = useStyles()
    const colors = useColors()
    return (
        <Pressable44
            onPress={onPress}
            accessibilityRole="link"
            accessibilityLabel={label}
            style={styles.row}
            pressedStyle={styles.pressed}
            testID={testID}
        >
            <Text style={styles.label}>{label}</Text>
            {external ? (
                <ExternalLinkIcon size={iconSizes.small} color={colors.secondary} />
            ) : (
                <ChevronRightIcon size={iconSizes.small} color={colors.secondary} />
            )}
        </Pressable44>
    )
}

const useStyles = createStyles(({ colors }) => ({
    row: {
        alignSelf: 'flex-start',
        flexDirection: 'row',
        alignItems: 'center',
        gap: 6,
        minHeight: ROW_HEIGHT,
    },
    pressed: {
        opacity: 0.6,
    },
    label: {
        fontSize: 15,
        lineHeight: lineHeight(15),
        fontWeight: '500',
        color: colors.ink,
    },
}))
