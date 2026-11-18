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
import { iconSizes } from '@/ui/tokens'

import { trackLiveSetupOpened } from './analytics'
import { LiveCard } from './LiveCard'
import { LiveMeanwhile } from './LiveMeanwhile'

interface LiveNoTrafficProps {
    state: 'quiet' | 'not_set_up'
    scope: ProjectScope | null
    mobile?: boolean
}

/** Live without events: why it is empty, and the Meanwhile list in place of the cards. */
export function LiveNoTraffic({ state, scope, mobile = false }: LiveNoTrafficProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const router = useRouter()
    const setupUrl = safeHttpsUrl(viewWebUrl(scope, '/onboarding') ?? '')
    const openSetup = (): void => {
        if (setupUrl) {
            trackLiveSetupOpened()
            Linking.openURL(setupUrl).catch(() => undefined)
        }
    }
    return (
        <View style={styles.content}>
            <LiveCard>
                {state === 'quiet' ? (
                    <StateView
                        icon={<LiveIcon size={iconSizes.empty} color={colors.tertiary} />}
                        title="Quiet right now"
                        message={
                            mobile
                                ? 'No mobile events in the last 30 minutes. Live keeps checking.'
                                : 'No events in the last 30 minutes. Live keeps checking.'
                        }
                        style={styles.state}
                        testID="live-quiet"
                    />
                ) : (
                    <StateView
                        icon={<GlobeIcon size={iconSizes.empty} color={colors.tertiary} />}
                        title="Install PostHog to see live activity"
                        message="This project has not sent an event yet. Add PostHog to your website or mobile app to see activity here."
                        actionLabel="Open setup guide"
                        onAction={openSetup}
                        actionDisabledReason={
                            setupUrl ? undefined : scope ? 'Not available over http' : 'Not in the demo'
                        }
                        secondaryActionLabel="Open Views"
                        onSecondaryAction={() => router.navigate('/(tabs)/views')}
                        style={styles.state}
                        testID="live-not-set-up"
                    />
                )}
            </LiveCard>
            <LiveMeanwhile />
        </View>
    )
}

const useStyles = createStyles(() => ({
    content: {
        gap: 12,
    },
    // The card's 14 pt padding plus these match the empty state's padding inside a card.
    state: {
        paddingHorizontal: 2,
        paddingVertical: 18,
    },
}))
