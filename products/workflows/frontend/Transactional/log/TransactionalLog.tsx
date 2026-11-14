import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonSegmentedButton } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { transactionalTemplatesLogic } from '../transactionalTemplatesLogic'
import { TransactionalEmailLog } from './TransactionalEmailLog'
import { TransactionalPushLog } from './TransactionalPushLog'

type LogChannel = 'email' | 'push'

// pinned: URL search param of the Log tab - renaming breaks shared links
const CHANNEL_PARAM = 'channel'

/** The Log tab. Push sends get their own view, offered only once the project has a push notification to send. */
export function TransactionalLog(): JSX.Element {
    const { sendablePushTemplates } = useValues(transactionalTemplatesLogic)
    const { searchParams, location, hashParams } = useValues(router)
    const { replace } = useActions(router)

    const hasPush = useFeatureFlag('WORKFLOWS_TRANSACTIONAL_PUSH_API') && sendablePushTemplates.length > 0
    const channel: LogChannel = hasPush && searchParams[CHANNEL_PARAM] === 'push' ? 'push' : 'email'

    return (
        <div className="flex flex-col gap-2">
            {hasPush && (
                <LemonSegmentedButton<LogChannel>
                    size="small"
                    value={channel}
                    onChange={(next) => {
                        const params = { ...searchParams }
                        if (next === 'push') {
                            params[CHANNEL_PARAM] = 'push'
                        } else {
                            delete params[CHANNEL_PARAM]
                        }
                        replace(location.pathname, params, hashParams)
                    }}
                    options={[
                        { value: 'email', label: 'Email', 'data-attr': 'transactional-log-channel-email' },
                        { value: 'push', label: 'Push', 'data-attr': 'transactional-log-channel-push' },
                    ]}
                    className="max-w-full self-start"
                />
            )}
            {channel === 'push' ? <TransactionalPushLog /> : <TransactionalEmailLog />}
        </div>
    )
}
