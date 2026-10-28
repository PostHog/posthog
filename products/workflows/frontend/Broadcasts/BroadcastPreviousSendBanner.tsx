import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { Link } from 'lib/lemon-ui/Link'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { broadcastPreviousSendLogic } from './broadcastPreviousSendLogic'

export function BroadcastPreviousSendBanner({ sourceRecord }: { sourceRecord: string }): JSX.Element | null {
    const { previousSend, sentCount } = useValues(broadcastPreviousSendLogic({ sourceRecord }))
    if (!previousSend) {
        return null
    }
    const message =
        previousSend.state === 'sent' && previousSend.job
            ? `You already emailed about this on ${dayjs(previousSend.job.created_at).format('MMMM D, YYYY')}${
                  sentCount ? ` (${pluralize(sentCount, 'person', 'people')})` : ''
              }.`
            : previousSend.state === 'sending'
              ? 'A broadcast about this is sending now.'
              : 'A broadcast about this is already scheduled.'
    return (
        <div data-attr="broadcast-previous-send">
            <LemonBanner type="warning">
                {message}{' '}
                <Link
                    to={urls.broadcast(previousSend.broadcastId)}
                    target="_blank"
                    data-attr="broadcast-previous-send-link"
                >
                    View that broadcast
                </Link>
                .
            </LemonBanner>
        </div>
    )
}
