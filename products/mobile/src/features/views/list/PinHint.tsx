import type { ReactElement } from 'react'
import { Text } from 'react-native'
import Animated, { FadeIn, useReducedMotion } from 'react-native-reanimated'

import { CloseIcon } from '@/ui/icons/CloseIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { motion, radii, type } from '@/ui/tokens'

/** The one-line callout under a pin that says the pin has a long-press menu. */
export function PinHint({ onDismiss }: { onDismiss: () => void }): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const reduceMotion = useReducedMotion()
    return (
        <Animated.View
            entering={reduceMotion ? undefined : FadeIn.duration(motion.fade)}
            style={styles.hint}
            testID="views-pin-hint"
        >
            <Text style={styles.text}>Long press a pin to change how it shows.</Text>
            <Pressable44
                onPress={onDismiss}
                accessibilityLabel="Dismiss"
                pressedBackground={colors.blueHighlight}
                style={styles.close}
                testID="views-pin-hint-dismiss"
            >
                <CloseIcon size={12} color={colors.blue} />
            </Pressable44>
        </Animated.View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    hint: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 4,
        paddingLeft: 12,
        paddingRight: 2,
        borderRadius: radii.tile,
        backgroundColor: colors.blueHighlight,
    },
    text: {
        ...type.meta,
        flex: 1,
        color: colors.blue,
        paddingVertical: 9,
    },
    close: {
        width: 32,
        height: 32,
        alignItems: 'center',
        justifyContent: 'center',
        borderRadius: radii.markLarge,
    },
}))
