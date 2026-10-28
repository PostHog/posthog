import { useActions, useMountedLogic, useValues } from 'kea'
import { ReactNode } from 'react'

import { LemonBadge, LemonSegmentedButton } from '@posthog/lemon-ui'

import { watchPicksLogic } from '../watchPicksLogic'
import { watchPicksStarterLogic } from '../watchPicksStarterLogic'
import { WatchPicksList } from './WatchPicksList'

interface WatchPicksListColumnProps {
    recordingsList: ReactNode
}

export function WatchPicksListColumn({ recordingsList }: WatchPicksListColumnProps): JSX.Element {
    const picksLogic = useMountedLogic(watchPicksLogic)
    const { effectiveListMode, unwatchedCount } = useValues(picksLogic)
    const { setListMode } = useActions(picksLogic)
    useMountedLogic(watchPicksStarterLogic(picksLogic.props))

    return (
        <>
            <LemonSegmentedButton
                size="small"
                fullWidth
                className="mb-2"
                value={effectiveListMode}
                onChange={setListMode}
                options={[
                    {
                        value: 'picks',
                        label: (
                            <span className="flex items-center gap-1">
                                <span>What to watch</span>
                                {unwatchedCount > 0 && (
                                    <LemonBadge.Number count={unwatchedCount} size="small" status="muted" />
                                )}
                            </span>
                        ),
                        'data-attr': 'vision-watch-picks-mode-picks',
                    },
                    { value: 'recordings', label: 'All recordings', 'data-attr': 'vision-watch-picks-mode-recordings' },
                ]}
            />
            {effectiveListMode === 'picks' ? <WatchPicksList /> : recordingsList}
        </>
    )
}
