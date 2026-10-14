import { type ReactElement, useEffect } from 'react'
import { StyleSheet, View } from 'react-native'

import { useSignOutAction } from '@/features/settings/useSignOut'
import { LockIcon } from '@/ui/icons/LockIcon'
import { StateView } from '@/ui/StateView'
import { colors, radii } from '@/ui/tokens'

import { trackViewsReauthShown } from '../analytics'
import type { ViewsAccess } from '../useViewsAccess'

/**
 * Views needs scopes that an older sign-in did not grant, and a token refresh never adds them. One new sign-in fixes
 * it, so the state offers it; the inbox and chats keep working until then.
 */
export function ViewsReauthState({ access }: { access: ViewsAccess }): ReactElement {
    const signOut = useSignOutAction()
    const { missingScope } = access
    useEffect(() => {
        trackViewsReauthShown({ missingScope })
    }, [missingScope])
    const message =
        access.state === 'personal-key-missing-scopes'
            ? 'Add dashboard:read, insight:read and file_system_shortcut:write to your key.'
            : 'PostHog needs a new permission to show dashboards and insights on this phone.'
    return (
        <StateView
            icon={
                <View style={styles.icon}>
                    <LockIcon size={26} color={colors.muted} />
                </View>
            }
            title="Sign in again to see your views"
            message={message}
            actionLabel="Sign in again"
            onAction={() => void signOut.run()}
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
