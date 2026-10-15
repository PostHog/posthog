import type { ErrorBoundaryProps } from 'expo-router'
import type { ReactElement } from 'react'
import { StyleSheet, View } from 'react-native'

import { WarningIcon } from './icons/WarningIcon'
import { StateView } from './StateView'
import { colors, iconSizes } from './tokens'

/** Shown by Expo Router when a screen throws while rendering. */
export function RouteErrorBoundary({ error, retry }: ErrorBoundaryProps): ReactElement {
    return (
        <View style={styles.screen}>
            <StateView
                icon={<WarningIcon size={iconSizes.empty} color={colors.tertiary} />}
                title="This screen couldn't load"
                message={error.message}
                actionLabel="Try again"
                onAction={() => void retry()}
            />
        </View>
    )
}

const styles = StyleSheet.create({
    screen: {
        flex: 1,
        backgroundColor: colors.background,
    },
})
