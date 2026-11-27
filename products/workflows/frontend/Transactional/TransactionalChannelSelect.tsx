import { LemonSelect } from '@posthog/lemon-ui'
import { Button, Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { CHANNEL_OPTIONS, TransactionalChannel, useTransactionalChannel } from './useTransactionalChannel'

/** Picks email or push. Renders nothing until the project can send push. */
export function TransactionalChannelSelect({ dataAttr }: { dataAttr: string }): JSX.Element | null {
    const { hasPush, channel, setChannel } = useTransactionalChannel()
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (!hasPush) {
        return null
    }

    if (!todayRailNav) {
        return (
            <LemonSelect<TransactionalChannel>
                size="small"
                value={channel}
                onChange={setChannel}
                options={CHANNEL_OPTIONS}
                data-attr={dataAttr}
            />
        )
    }

    return (
        <Select<TransactionalChannel> value={channel} onValueChange={(value) => value !== null && setChannel(value)}>
            <SelectTrigger render={<Button variant="outline" left />} data-attr={dataAttr}>
                <SelectValue>
                    {(value: TransactionalChannel) => CHANNEL_OPTIONS.find((option) => option.value === value)?.label}
                </SelectValue>
            </SelectTrigger>
            <SelectContent align="end" alignItemWithTrigger={false}>
                {CHANNEL_OPTIONS.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                        {option.label}
                    </SelectItem>
                ))}
            </SelectContent>
        </Select>
    )
}
