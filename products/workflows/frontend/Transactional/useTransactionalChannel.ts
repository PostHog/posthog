import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { transactionalTemplatesLogic } from './transactionalTemplatesLogic'

export type TransactionalChannel = 'email' | 'push'

// pinned: URL search param of the Log and Metrics tabs - renaming breaks shared links
const CHANNEL_PARAM = 'channel'

export const CHANNEL_OPTIONS: { value: TransactionalChannel; label: string }[] = [
    { value: 'email', label: 'Email' },
    { value: 'push', label: 'Push' },
]

/** Push is offered only once the project has a push notification it can send. */
export function useTransactionalChannel(): {
    hasPush: boolean
    channel: TransactionalChannel
    setChannel: (channel: TransactionalChannel) => void
} {
    const { sendablePushTemplates, transactionalTemplatesLoading, transactionalTemplatesFailed } =
        useValues(transactionalTemplatesLogic)
    const { searchParams, location, hashParams } = useValues(router)
    const { replace } = useActions(router)

    const pushEnabled = useFeatureFlag('WORKFLOWS_TRANSACTIONAL_PUSH_API')
    const hasPush = pushEnabled && sendablePushTemplates.length > 0
    // A reload of a push link stays on push while the templates load, instead of showing the email log first. A failed
    // load stays on push too, because it says nothing about whether the project has push notifications.
    const channel: TransactionalChannel =
        searchParams[CHANNEL_PARAM] === 'push' &&
        (hasPush || (pushEnabled && (transactionalTemplatesLoading || transactionalTemplatesFailed)))
            ? 'push'
            : 'email'

    const setChannel = (next: TransactionalChannel): void => {
        const params = { ...searchParams }
        if (next === 'push') {
            params[CHANNEL_PARAM] = 'push'
        } else {
            delete params[CHANNEL_PARAM]
        }
        replace(location.pathname, params, hashParams)
    }

    return { hasPush, channel, setChannel }
}

/** Keeps push selected when moving between the Log and Metrics tabs. */
export function withTransactionalChannel(url: string, channel: TransactionalChannel): string {
    return channel === 'push' ? combineUrl(url, { [CHANNEL_PARAM]: 'push' }).url : url
}
