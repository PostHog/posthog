import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconEye } from '@posthog/icons'
import { LemonButton, LemonSwitch } from '@posthog/lemon-ui'

import { TimezoneSelect } from 'lib/components/TimezoneSelect'
import { Popover } from 'lib/lemon-ui/Popover'

import { logsViewerSettingsLogic } from './logsViewerSettingsLogic'

/**
 * Display settings for the logs list — wrap + timezone. Timezone is shared state with the
 * date range picker's timezone control (logsViewerSettingsLogic); both surfaces write it.
 */
export const LogsViewSettings = (): JSX.Element => {
    const [isOpen, setIsOpen] = useState(false)
    const { wrapBody, timezone } = useValues(logsViewerSettingsLogic)
    const { setWrapBody, setTimezone } = useActions(logsViewerSettingsLogic)

    return (
        <Popover
            visible={isOpen}
            onClickOutside={() => setIsOpen(false)}
            placement="bottom-end"
            overlay={
                <div className="p-2 w-72 flex flex-col gap-2">
                    <LemonSwitch
                        checked={wrapBody}
                        onChange={setWrapBody}
                        label="Wrap log lines"
                        size="small"
                        fullWidth
                        bordered
                    />
                    <div className="flex items-center justify-between gap-2">
                        <span className="text-sm">Timezone display</span>
                        <TimezoneSelect value={timezone} onChange={setTimezone} size="small" />
                    </div>
                </div>
            }
        >
            <LemonButton
                size="small"
                type="secondary"
                icon={<IconEye />}
                onClick={() => setIsOpen(!isOpen)}
                tooltip="View settings"
                aria-label="View settings"
                data-attr="logs-view-settings"
            />
        </Popover>
    )
}
