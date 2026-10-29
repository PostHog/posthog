import { type ReactElement, useState } from 'react'
import { Text } from 'react-native'

import { useAuthStore } from '@/auth/authStore'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'

import { SignOutConfirm } from './SignOutConfirm'
import { useExitDemo, useSignOutAction } from './useSignOut'

export function SignOutSection(): ReactElement {
    const styles = useStyles()
    const colors = useColors()
    const signedIn = useAuthStore((state) => state.signedIn)
    const exitDemo = useExitDemo()
    const signOut = useSignOutAction()
    const [confirming, setConfirming] = useState(false)

    if (!signedIn) {
        return (
            <Pressable44
                onPress={exitDemo}
                pressedBackground={colors.sunken}
                style={styles.button}
                testID="settings-exit-demo"
            >
                <Text style={styles.buttonText}>Exit demo</Text>
            </Pressable44>
        )
    }

    if (!confirming) {
        return (
            <Pressable44
                onPress={() => setConfirming(true)}
                pressedBackground={colors.sunken}
                style={styles.button}
                testID="settings-sign-out"
            >
                <Text style={styles.buttonText}>Sign out</Text>
            </Pressable44>
        )
    }

    return (
        <SignOutConfirm
            from="settings"
            pending={signOut.pending}
            error={signOut.error}
            onCancel={() => {
                signOut.clearError()
                setConfirming(false)
            }}
            onConfirm={() => void signOut.run()}
            style={styles.confirm}
            testIDPrefix="settings"
        />
    )
}

const useStyles = createStyles(({ colors }) => ({
    button: {
        marginTop: 32,
        height: 52,
        borderRadius: radii.card,
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: colors.surface,
        alignItems: 'center',
        justifyContent: 'center',
    },
    buttonText: {
        ...type.button,
        color: colors.orange,
    },
    confirm: {
        marginTop: 32,
        padding: 16,
        borderRadius: radii.card,
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: colors.surface,
    },
}))
