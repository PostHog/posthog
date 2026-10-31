import { type ReactElement, useEffect } from 'react'
import { View } from 'react-native'

import { FEATURE_SCOPES, type ScopedFeature } from '@/api/scopeErrors'
import { useSignOutAction } from '@/features/settings/useSignOut'
import { LockIcon } from '@/ui/icons/LockIcon'
import { StateView } from '@/ui/StateView'
import { createStyles, useColors } from '@/ui/theme'
import { radii } from '@/ui/tokens'

import { trackViewsReauthShown } from './analytics'
import type { ViewsAccess } from './useViewsAccess'

interface FeatureCopy {
    unavailableTitle: string
    /** What the app cannot read, as in "PostHog doesn't let this app read …". */
    reads: string
    reauthTitle: string
    /** What the new permission shows, as in "PostHog needs a new permission to show …". */
    shows: string
}

const COPY: Record<ScopedFeature, FeatureCopy> = {
    views: {
        unavailableTitle: "Views isn't available yet",
        reads: 'dashboards and insights',
        reauthTitle: 'Sign in again to see your views',
        shows: 'dashboards and insights',
    },
    errors: {
        unavailableTitle: "Errors aren't available yet",
        reads: 'error tracking',
        reauthTitle: 'Sign in again to see errors',
        shows: 'error tracking issues',
    },
    replay: {
        unavailableTitle: "Sessions aren't available yet",
        reads: 'session recordings',
        reauthTitle: 'Sign in again to see sessions',
        shows: 'session recordings',
    },
}

function scopeList(scopes: readonly string[]): string {
    return scopes.length < 2 ? scopes.join('') : `${scopes.slice(0, -1).join(', ')} and ${scopes[scopes.length - 1]}`
}

/**
 * A feature needs scopes that an older sign-in did not grant, and a token refresh never adds them. One new sign-in fixes
 * it, so the state offers it; the inbox and chats keep working until then. When the last sign-in asked for the scope
 * and still did not get it, a new sign-in gets the same grant, so the state explains that and offers no sign-in.
 */
export function ViewsReauthState({
    access,
    feature = 'views',
}: {
    access: ViewsAccess
    feature?: ScopedFeature
}): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const signOut = useSignOutAction()
    const { missingScope, state } = access
    useEffect(() => {
        if (state !== 'ok') {
            trackViewsReauthShown({ missingScope, state, feature })
        }
    }, [missingScope, state, feature])
    const copy = COPY[feature]
    const icon = (
        <View style={styles.icon}>
            <LockIcon size={26} color={colors.muted} />
        </View>
    )
    if (state === 'unavailable') {
        return (
            <StateView
                icon={icon}
                title={copy.unavailableTitle}
                message={`PostHog doesn't let this app read ${copy.reads} yet, so signing in again won't help. Your inbox and chats still work.`}
                testID={`${feature}-unavailable`}
            />
        )
    }
    const message =
        state === 'personal-key-missing-scopes'
            ? `Add ${scopeList(FEATURE_SCOPES[feature])} to your key.`
            : `PostHog needs a new permission to show ${copy.shows} on this phone.`
    return (
        <StateView
            icon={icon}
            title={copy.reauthTitle}
            message={message}
            actionLabel="Sign in again"
            onAction={() => void signOut.run()}
            testID={`${feature}-reauth`}
        />
    )
}

const useStyles = createStyles(({ colors }) => ({
    icon: {
        width: 52,
        height: 52,
        borderRadius: radii.option,
        borderWidth: 1,
        borderColor: colors.hairline,
        backgroundColor: colors.surface,
        alignItems: 'center',
        justifyContent: 'center',
    },
}))
