import { useActions, useValues } from 'kea'

import { IconMinusSquare, IconPlusSquare, IconRefresh } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { AppShortcut } from 'lib/components/AppShortcuts/AppShortcut'
import { keyBinds } from 'lib/components/AppShortcuts/shortcuts'
import { IconPauseCircle, IconPlayCircle } from 'lib/lemon-ui/icons'
import { Scene } from 'scenes/sceneTypes'

import { LogsFilterGroup } from 'products/logs/frontend/components/filters/LogsFilters/FilterGroup'
import { DateRangeFilter } from 'products/logs/frontend/filters/DateRangeFilter'
import { ServiceFilter } from 'products/logs/frontend/filters/ServiceFilter'
import { SeverityLevelsFilter } from 'products/logs/frontend/filters/SeverityLevelsFilter'
import { logsLogic } from 'products/logs/frontend/logsLogic'

export const LogsFilters = (): JSX.Element => {
    const { logsLoading, liveTailRunning, liveTailDisabledReason } = useValues(logsLogic)
    const { runQuery, zoomDateRange, setLiveTailRunning } = useActions(logsLogic)

    return (
        <div className="flex flex-col gap-y-1.5">
            <div className="flex justify-between gap-y-2 flex-wrap-reverse">
                <div className="flex gap-x-1 gap-y-2 flex-wrap">
                    <SeverityLevelsFilter />
                    <ServiceFilter />
                </div>
                <div className="flex gap-x-1">
                    <LemonButton
                        size="small"
                        icon={<IconMinusSquare />}
                        type="secondary"
                        onClick={() => zoomDateRange(2)}
                    />
                    <LemonButton
                        size="small"
                        icon={<IconPlusSquare />}
                        type="secondary"
                        onClick={() => zoomDateRange(0.5)}
                    />
                    <DateRangeFilter />

                    <LemonButton
                        size="small"
                        icon={<IconRefresh />}
                        type="secondary"
                        onClick={() => runQuery()}
                        loading={logsLoading || liveTailRunning}
                        disabledReason={liveTailRunning ? 'Disable live tail to manually refresh' : undefined}
                    >
                        {liveTailRunning ? 'Tailing...' : logsLoading ? 'Loading...' : 'Search'}
                    </LemonButton>
                    <AppShortcut
                        name="LogsLiveTail"
                        keybind={[keyBinds.edit]}
                        intent={liveTailRunning ? 'Stop live tail' : 'Start live tail'}
                        interaction="click"
                        scope={Scene.Logs}
                    >
                        <LemonButton
                            size="small"
                            type={liveTailRunning ? 'primary' : 'secondary'}
                            icon={liveTailRunning ? <IconPauseCircle /> : <IconPlayCircle />}
                            onClick={() => setLiveTailRunning(!liveTailRunning)}
                            disabledReason={liveTailRunning ? undefined : liveTailDisabledReason}
                        >
                            Live tail
                        </LemonButton>
                    </AppShortcut>
                </div>
            </div>
            <LogsFilterGroup />
        </div>
    )
}
