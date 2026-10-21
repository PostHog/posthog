import type { ReactElement } from 'react'
import { View } from 'react-native'

import { PostHogLogomark } from '@/ui/icons/PostHogLogomark'
import { createStyles } from '@/ui/theme'

export function BootSplash(): ReactElement {
    const styles = useStyles()
    return (
        <View style={styles.screen} accessibilityLabel="Loading PostHog" testID="boot-splash">
            <PostHogLogomark height={65} />
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
