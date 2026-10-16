import type { ReactElement } from 'react'
import { StyleSheet, View } from 'react-native'

import { PostHogLogomark } from '@/ui/icons/PostHogLogomark'
import { colors } from '@/ui/tokens'

export function BootSplash(): ReactElement {
    return (
        <View style={styles.screen} accessibilityLabel="Loading PostHog" testID="boot-splash">
            <PostHogLogomark height={65} />
        </View>
    )
}

const styles = StyleSheet.create({
    screen: {
        flex: 1,
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: colors.background,
    },
})
