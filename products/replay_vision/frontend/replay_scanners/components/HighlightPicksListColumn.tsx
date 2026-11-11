import { useActions, useMountedLogic, useValues } from 'kea'
import { ReactNode } from 'react'

import { LemonBadge, LemonSegmentedButton } from '@posthog/lemon-ui'

import { highlightPicksLogic } from '../highlightPicksLogic'
import { highlightPicksStarterLogic } from '../highlightPicksStarterLogic'
import { HighlightPicksList } from './HighlightPicksList'

interface HighlightPicksListColumnProps {
    recordingsList: ReactNode
}

export function HighlightPicksListColumn({ recordingsList }: HighlightPicksListColumnProps): JSX.Element {
    const picksLogic = useMountedLogic(highlightPicksLogic)
    const { effectiveListMode, unwatchedCount } = useValues(picksLogic)
    const { setListMode } = useActions(picksLogic)
    useMountedLogic(highlightPicksStarterLogic(picksLogic.props))

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
                                <span>Highlights</span>
                                {unwatchedCount > 0 && (
                                    <LemonBadge.Number count={unwatchedCount} size="small" status="muted" />
                                )}
                            </span>
                        ),
                        'data-attr': 'vision-highlight-picks-mode-picks',
                    },
                    {
                        value: 'recordings',
                        label: 'All recordings',
                        'data-attr': 'vision-highlight-picks-mode-recordings',
                    },
                ]}
            />
            {effectiveListMode === 'picks' ? <HighlightPicksList /> : recordingsList}
        </>
    )
}
