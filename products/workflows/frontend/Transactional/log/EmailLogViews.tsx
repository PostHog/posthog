import { router } from 'kea-router'

import { LemonSegmentedButton } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { urls } from 'scenes/urls'

import { ReceivedEmails } from '../receiving/ReceivedEmails'
import { TransactionalEmailLog } from './TransactionalEmailLog'

/** Sending and receiving sit next to each other in one log, the way people think of a mailbox. */
export function EmailLogViews({ view }: { view: 'sent' | 'received' }): JSX.Element {
    const receivingEnabled = useFeatureFlag('WORKFLOWS_INBOUND_EMAIL')

    if (!receivingEnabled) {
        return <TransactionalEmailLog />
    }
    return (
        <div className="flex flex-col gap-3">
            <div>
                <LemonSegmentedButton
                    size="small"
                    value={view}
                    onChange={(next) =>
                        router.actions.push(
                            next === 'received' ? urls.transactionalReceived() : urls.transactionalLog()
                        )
                    }
                    options={[
                        { value: 'sent', label: 'Sending', 'data-attr': 'email-log-sending' },
                        { value: 'received', label: 'Receiving', 'data-attr': 'email-log-receiving' },
                    ]}
                />
            </div>
            {view === 'received' ? <ReceivedEmails /> : <TransactionalEmailLog />}
        </div>
    )
}
