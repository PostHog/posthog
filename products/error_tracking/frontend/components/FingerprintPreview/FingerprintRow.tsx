import { useValues } from 'kea'

import { IconSearch } from '@posthog/icons'

import { dayjs } from 'lib/dayjs'
import { Button, Text, Tooltip, TooltipContent, TooltipTrigger } from 'lib/ui/quill'
import { teamLogic } from 'scenes/teamLogic'

import { FingerprintLabel } from './FingerprintLabel'
import { FingerprintSample } from './fingerprintSamplesLogic'

interface FingerprintRowProps {
    fingerprint: string
    firstSeen: string
    sample?: FingerprintSample
    onSelect: () => void
    onFindSimilar: () => void
}

export function FingerprintRow({
    fingerprint,
    firstSeen,
    sample,
    onSelect,
    onFindSimilar,
}: FingerprintRowProps): JSX.Element {
    const { timezone } = useValues(teamLogic)
    const firstSeenAt = dayjs(firstSeen).tz(timezone)

    return (
        <div className="grid min-h-11 grid-cols-[minmax(0,1fr)_auto_auto] items-start gap-x-2">
            <Tooltip>
                <TooltipTrigger
                    render={
                        <Button
                            variant="default"
                            size="sm"
                            className="h-auto w-full min-w-0 justify-start px-1.5 py-1 text-xs"
                            data-attr="error-tracking-fingerprint-list-item"
                            onClick={onSelect}
                        />
                    }
                >
                    <FingerprintLabel fingerprint={fingerprint} sample={sample} />
                </TooltipTrigger>
                <TooltipContent side="right">
                    <div className="flex max-w-80 flex-col gap-0.5">
                        {sample && (
                            <>
                                <span className="font-semibold">{sample.type}</span>
                                <span>{sample.value}</span>
                            </>
                        )}
                        <span className="break-all font-mono text-muted-alt">{fingerprint}</span>
                        <span>First seen {firstSeenAt.format('D MMM YYYY HH:mm')}</span>
                        <span className="text-muted-alt">Click to filter exceptions</span>
                    </div>
                </TooltipContent>
            </Tooltip>
            <Text size="xs" variant="muted" className="shrink-0 pt-1.5 tabular-nums">
                {firstSeenAt.format('D MMM YYYY')}
            </Text>
            <Tooltip>
                <TooltipTrigger
                    render={
                        <Button
                            variant="default"
                            size="icon-sm"
                            aria-label="Find similar fingerprints"
                            data-attr="error-tracking-fingerprint-find-similar"
                            onClick={onFindSimilar}
                        />
                    }
                >
                    <IconSearch />
                </TooltipTrigger>
                <TooltipContent>Find similar</TooltipContent>
            </Tooltip>
        </div>
    )
}
