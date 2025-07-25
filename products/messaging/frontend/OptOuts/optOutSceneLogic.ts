import { kea, path, actions, connect } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

import type { optOutSceneLogicType } from './optOutSceneLogicType'
import { userLogic } from 'scenes/userLogic'
import { lemonToast } from '@posthog/lemon-ui'

export const optOutSceneLogic = kea<optOutSceneLogicType>([
    path(['products', 'messaging', 'frontend', 'OptOuts', 'optOutSceneLogic']),
    connect({
        values: [userLogic, ['user']],
    }),

    actions({
        loadUnsubscribeLink: true,
    }),

    loaders(({ values }) => ({
        preferencesUrl: {
            __default: null as string | null,
            openPreferencesPage: async (): Promise<string | null> => {
                if (!values.user?.email) {
                    lemonToast.error('User email not found')
                    return null
                }

                try {
                    const newPreferencesUrl = await api.messaging.generateMessagingPreferencesLink()
                    if (!newPreferencesUrl) {
                        lemonToast.error('Failed to generate messaging preferences link')
                        return null
                    }
                    window.open(newPreferencesUrl, '_blank')
                    return newPreferencesUrl
                } catch {
                    lemonToast.error('Failed to generate messaging preferences link')
                    return null
                }
            },
        },
    })),
])
