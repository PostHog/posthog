import { useRouter } from 'expo-router'
import type { ReactElement } from 'react'
import { Linking, View } from 'react-native'

import type { ProjectScope } from '@/api/reports'
import { viewWebUrl } from '@/features/views/webLinks'
import { safeHttpsUrl } from '@/lib/urls'
import { GlobeIcon } from '@/ui/icons/GlobeIcon'
import { LiveIcon } from '@/ui/icons/LiveIcon'
import { StateView } from '@/ui/StateView'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, radii } from '@/ui/tokens'

import { trackLiveSetupOpened } from './analytics'
import { LiveMeanwhile } from './LiveMeanwhile'

interface LiveNoTrafficProps {
    state: 'quiet' | 'not_set_up'
    scope: ProjectScope | null
}

/** Live without events: why it is empty, and the Meanwhile list in place of the cards. */
export function LiveNoTraffic({ state, scope }: LiveNoTrafficProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const router = useRouter()
    const setupUrl = viewWebUrl(scope, '/onboarding')
    const openSetup = (): void => {
        const safe = setupUrl ? safeHttpsUrl(setupUrl) : undefined
        if (safe) {
            trackLiveSetupOpened()
            Linking.openURL(safe).catch(() => undefined)
        }
    }
    return (
        <View style={styles.content}>
            <View style={styles.card}>
                {state === 'quiet' ? (
                    <StateView
                        icon={<LiveIcon size={iconSizes.empty} color={colors.tertiary} />}
                        title="Quiet right now"
                        message="No events in the last 30 minutes. Live fills in the moment someone shows up."
                        style={styles.state}
                        testID="live-quiet"
                    />
                ) : (
                    <StateView
                        icon={<GlobeIcon size={iconSizes.empty} color={colors.tertiary} />}
                        title="Install PostHog to see live activity"
                        message="This project has not sent an event yet. Add the web snippet or an SDK and Live fills in within seconds."
                        actionLabel="Open setup guide"
                        onAction={openSetup}
                        actionDisabledReason={setupUrl ? undefined : 'Not in the demo'}
                        secondaryActionLabel="Open Views"
                        onSecondaryAction={() => router.navigate('/(tabs)/views')}
                        style={styles.state}
                        testID="live-not-set-up"
                    />
                )}
            </View>
            <LiveMeanwhile />
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    content: {
        gap: 12,
    },
    card: {
        borderRadius: radii.card,
        borderWidth: 1,
        borderColor: colors.hairline,
        backgroundColor: colors.surface,
    },
    state: {
        paddingHorizontal: 16,
        paddingVertical: 32,
    },
}))
