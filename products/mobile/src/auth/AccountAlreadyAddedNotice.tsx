import type { ReactElement } from 'react'
import { Linking, Text, View } from 'react-native'

import { track } from '@/lib/analytics'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'

import { regionForHost } from './regions'
import type { AccountAlreadyAddedError } from './signInErrors'

interface AccountAlreadyAddedNoticeProps {
    error: AccountAlreadyAddedError
    pending: boolean
    onRetry: () => void
}

/**
 * The browser signed in as an account this phone already has. The app cannot sign the browser out, because the web
 * app's logout takes a form post, so it opens PostHog where the user can sign out.
 */
export function AccountAlreadyAddedNotice({ error, pending, onRetry }: AccountAlreadyAddedNoticeProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const openBrowser = (): void => {
        track('mobile_account_browser_opened', { region: regionForHost(error.host) })
        Linking.openURL(error.host).catch(() => undefined)
    }
    return (
        <View style={styles.box} accessibilityRole="alert" testID="sign-in-already-added">
            <Text style={styles.text}>
                Your browser is still signed in to PostHog as {error.email}, and that account is already on this phone.
                To add a different account, sign out of PostHog in the browser, then try again.
            </Text>
            <View style={styles.actions}>
                <Pressable44
                    onPress={openBrowser}
                    accessibilityRole="link"
                    accessibilityHint="Opens in your browser"
                    pressedBackground={colors.sunken}
                    style={styles.button}
                    testID="sign-in-open-browser"
                >
                    <Text style={styles.buttonText}>Open PostHog in the browser</Text>
                </Pressable44>
                <Pressable44
                    onPress={onRetry}
                    disabled={pending}
                    accessibilityState={{ busy: pending, disabled: pending }}
                    pressedBackground={colors.sunken}
                    style={styles.button}
                    testID="sign-in-retry"
                >
                    <Text style={styles.buttonText}>Try again</Text>
                </Pressable44>
            </View>
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    box: {
        gap: 10,
        alignItems: 'flex-start',
        padding: 12,
        borderRadius: radii.card,
        backgroundColor: colors.sunken,
    },
    text: {
        ...type.metaSmall,
        color: colors.ink,
    },
    actions: {
        flexDirection: 'row',
        flexWrap: 'wrap',
        gap: 8,
    },
    button: {
        height: 36,
        paddingHorizontal: 14,
        borderRadius: radii.pill,
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: colors.surface,
        alignItems: 'center',
        justifyContent: 'center',
    },
    buttonText: {
        ...type.buttonSmall,
        color: colors.ink,
    },
}))
