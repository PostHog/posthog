import { useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

/** Opens the sending domain page when the wizard flag is on. Returns null when the flag is off, so the caller keeps its modal. */
export function useStartEmailDomainSetup(entry: 'channels' | 'broadcast'): (() => void) | null {
    const { featureFlags } = useValues(featureFlagLogic)
    if (!featureFlags[FEATURE_FLAGS.WORKFLOWS_EMAIL_DOMAIN_WIZARD]) {
        return null
    }
    return () => {
        // pinned: analytics event name
        posthog.capture('email domain setup started', { entry })
        router.actions.push(urls.workflowsEmailDomain('new'))
    }
}
