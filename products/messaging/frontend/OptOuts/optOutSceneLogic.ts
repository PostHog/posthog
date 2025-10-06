import { actions, connect, kea, path } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { userLogic } from 'scenes/userLogic'

import type { optOutSceneLogicType } from './optOutSceneLogicType'

export const optOutSceneLogic = kea<optOutSceneLogicType>([
    path(['products', 'messaging', 'frontend', 'OptOuts', 'optOutSceneLogic']),
    connect(() => ({
        values: [userLogic, ['user']],
    })),
    actions({
        loadUnsubscribeLink: true,
    }),
    loaders(({ values }) => ({
        preferencesUrl: {
            __default: null as string | null,
            openPreferencesPage: async (recipient?: string): Promise<string | null> => {
                if (!values.user?.email) {
                    lemonToast.error('User email not found')
                    return null
                }

                try {
                    const newPreferencesUrl = await api.messaging.generateMessagingPreferencesLink(recipient)
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
