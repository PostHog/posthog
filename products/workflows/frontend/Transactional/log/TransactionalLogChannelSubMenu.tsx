import { FilterRadioSubMenu } from '@posthog/quill'

import { CHANNEL_OPTIONS, TransactionalChannel, useTransactionalChannel } from '../useTransactionalChannel'

/** The Channel row of the log's filter menu. It switches the view, so it never counts as a filter. */
export function TransactionalLogChannelSubMenu(): JSX.Element | null {
    const { hasPush, channel, setChannel } = useTransactionalChannel()
    if (!hasPush) {
        return null
    }
    return (
        <FilterRadioSubMenu<TransactionalChannel>
            label="Channel"
            options={CHANNEL_OPTIONS}
            value={channel}
            onChange={setChannel}
            dataAttr="transactional-log-channel-filter"
        />
    )
}
