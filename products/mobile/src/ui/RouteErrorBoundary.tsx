import { type ErrorBoundaryProps, useSegments } from 'expo-router'
import { type ReactElement, useEffect } from 'react'
import { View } from 'react-native'

import { captureError, track } from '@/lib/analytics'
import { screenName } from '@/lib/useScreenTracking'

import { WarningIcon } from './icons/WarningIcon'
import { StateView } from './StateView'
import { createStyles, useColors } from './theme'
import { iconSizes } from './tokens'

/** Shown by Expo Router when a screen throws while rendering. */
export function RouteErrorBoundary({ error, retry }: ErrorBoundaryProps): ReactElement {
    const screen = screenName(useSegments())
    const colors = useColors()
    const styles = useStyles()

    // biome-ignore lint/correctness/useExhaustiveDependencies: one report per error, not per route change.
    useEffect(() => {
        track('mobile_screen_error_shown', { screen, error_name: error.name })
        captureError(error)
    }, [error])

    return (
        <View style={styles.screen}>
            <StateView
                icon={<WarningIcon size={iconSizes.empty} color={colors.tertiary} />}
                title="This screen couldn't load"
                message={error.message}
                actionLabel="Try again"
                onAction={() => {
                    track('mobile_screen_error_retried', { screen })
                    void retry()
                }}
            />
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    screen: {
        flex: 1,
        backgroundColor: colors.background,
    },
}))
