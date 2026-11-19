import { useValues } from 'kea'

import { Text } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'

import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'

export function QuillSuggestionsReadsNote(): JSX.Element {
    const { status } = useValues(warehouseSuggestionsLogic)

    return (
        <Text size="xs" variant="muted" render={<span />} className="min-w-0 flex-1">
            <span>{`Based on the last ${status?.window_days ?? 0} days of reads. Cached dashboard views aren't counted.`}</span>
            {status?.refreshed_at && (
                <>
                    <span> Updated </span>
                    <TZLabel time={status.refreshed_at} showPopover={false} />
                    <span>.</span>
                </>
            )}
        </Text>
    )
}
