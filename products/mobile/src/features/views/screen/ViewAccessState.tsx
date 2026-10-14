import { type ReactElement, useEffect } from 'react'
import { StyleSheet, View } from 'react-native'

import { useAuthStore } from '@/auth/authStore'
import { LockIcon } from '@/ui/icons/LockIcon'
import { StateView } from '@/ui/StateView'
import { colors, radii } from '@/ui/tokens'

import { trackViewsReauthShown } from '../analytics'
import type { ViewsAccess } from '../useViewsAccess'

const REAUTH_MESSAGE = 'PostHog needs a new permission to show dashboards and insights on this phone.'
const PERSONAL_KEY_MESSAGE = 'Add dashboard:read, insight:read and file_system_shortcut:write to your key.'

/** Views without its scopes: one new sign-in grants them. Inbox and Chats keep working meanwhile. */
export function ViewAccessState({ access }: { access: ViewsAccess }): ReactElement {
    const { missingScope } = access
    useEffect(() => {
        trackViewsReauthShown({ missingScope })
    }, [missingScope])
    return (
        <StateView
            icon={
                <View style={styles.icon}>
                    <LockIcon size={26} color={colors.muted} />
                </View>
            }
            title="Sign in again to see your views"
            message={access.state === 'personal-key-missing-scopes' ? PERSONAL_KEY_MESSAGE : REAUTH_MESSAGE}
            actionLabel="Sign in again"
            onAction={() => void useAuthStore.getState().signOut()}
            testID="views-reauth"
        />
    )
}

const styles = StyleSheet.create({
    icon: {
        width: 52,
        height: 52,
        borderRadius: radii.option,
        borderWidth: 1,
        borderColor: colors.hairline,
        backgroundColor: colors.white,
        alignItems: 'center',
        justifyContent: 'center',
    },
})
