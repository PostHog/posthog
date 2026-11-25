import { useState } from 'react'

import { IconCheck, IconX } from '@posthog/icons'
import { LemonSegmentedButton } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'
import { capitalizeFirstLetter } from 'lib/utils/strings'

import type { SourceFilterPreviewResponseApi } from 'products/signals/frontend/generated/api.schemas'

import { SourceFilterPreviewRecordRow } from './SourceFilterPreviewRecordRow'

export interface SourceFilterPreviewResultsProps {
    /** A preview response with status `ok` and at least one record in the window. */
    result: SourceFilterPreviewResponseApi
    sourceLabel: string
    noun: string
}

type PreviewSide = 'passing' | 'excluded'

function unreadableNote(count: number, noun: string): string {
    return count === 1
        ? `1 ${noun} is unreadable. It holds a value this filter can't read, so it never passes.`
        : `${humanFriendlyNumber(count)} ${noun}s are unreadable. They hold a value this filter can't read, so they never pass.`
}

export function SourceFilterPreviewResults({
    result,
    sourceLabel,
    noun,
}: SourceFilterPreviewResultsProps): JSX.Element {
    const [side, setSide] = useState<PreviewSide>('excluded')
    const nouns = `${noun}s`
    const records = side === 'passing' ? result.passing : result.excluded
    const emptyMessage =
        side === 'passing'
            ? `No recent ${nouns} pass, so no new reports would come from ${sourceLabel}.`
            : `No recent ${nouns} are excluded.`

    return (
        <>
            <LemonSegmentedButton
                fullWidth
                size="small"
                value={side}
                onChange={setSide}
                options={[
                    {
                        value: 'passing',
                        label: `Passes ${humanFriendlyNumber(result.passing_count)}`,
                        icon: <IconCheck />,
                        'data-attr': 'signal-source-filter-preview-passing',
                    },
                    {
                        value: 'excluded',
                        label: `Excluded ${humanFriendlyNumber(result.excluded_count)}`,
                        icon: <IconX />,
                        'data-attr': 'signal-source-filter-preview-excluded',
                    },
                ]}
            />
            {records.length > 0 ? (
                <ul className="flex flex-col divide-y divide-primary">
                    {records.map((record) => (
                        <SourceFilterPreviewRecordRow key={record.id} record={record} noun={noun} />
                    ))}
                </ul>
            ) : (
                <p className="m-0 py-3 text-sm text-secondary">{emptyMessage}</p>
            )}
            {side === 'excluded' && result.malformed_count > 0 && (
                <p className="m-0 text-xs text-muted">{unreadableNote(result.malformed_count, noun)}</p>
            )}
            <p className="m-0 text-xs text-muted">
                {`Shows the 10 newest of each. ${capitalizeFirstLetter(nouns)} that pass can still be skipped by guidance or as duplicates.`}
            </p>
        </>
    )
}
