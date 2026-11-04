import type { ReactElement } from 'react'
import { View } from 'react-native'

import { AnimatedLogomark } from '@/ui/icons/AnimatedLogomark'
import { createStyles } from '@/ui/theme'

export function BootSplash(): ReactElement {
    const styles = useStyles()
    return (
        <View
            style={styles.screen}
            accessible
            accessibilityLabel="Loading PostHog"
            accessibilityState={{ busy: true }}
            testID="boot-splash"
        >
            <AnimatedLogomark height={65} />
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    screen: {
        flex: 1,
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: colors.background,
    },
}))
