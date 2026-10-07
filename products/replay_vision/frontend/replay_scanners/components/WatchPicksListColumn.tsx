import { useActions, useValues } from 'kea'
import { ReactNode } from 'react'

import { LemonBadge, LemonSegmentedButton } from '@posthog/lemon-ui'

import { watchPicksLogic } from '../watchPicksLogic'
import { WatchPicksList } from './WatchPicksList'

interface WatchPicksListColumnProps {
    recordingsList: ReactNode
}

export function WatchPicksListColumn({ recordingsList }: WatchPicksListColumnProps): JSX.Element {
    const { listMode, picks } = useValues(watchPicksLogic)
    const { setListMode } = useActions(watchPicksLogic)

    return (
        <>
            <LemonSegmentedButton
                size="small"
                fullWidth
                className="mb-2"
                value={listMode}
                onChange={setListMode}
                options={[
                    { value: 'recordings', label: 'All recordings', 'data-attr': 'vision-watch-picks-mode-recordings' },
                    {
                        value: 'picks',
                        label: (
                            <span className="flex items-center gap-1">
                                <span>What to watch</span>
                                {picks && picks.length > 0 && (
                                    <LemonBadge.Number count={picks.length} size="small" status="muted" />
                                )}
                            </span>
                        ),
                        'data-attr': 'vision-watch-picks-mode-picks',
                    },
                ]}
            />
            {listMode === 'picks' ? <WatchPicksList /> : recordingsList}
        </>
    )
}
