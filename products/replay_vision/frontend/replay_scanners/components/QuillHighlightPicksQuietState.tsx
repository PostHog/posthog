import { useActions, useMountedLogic, useValues } from 'kea'

import * as noirPng from '@posthog/brand/hoggies/png/noir-1'
import { Button, Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@posthog/quill'

import { pngHoggie } from 'lib/brand/hoggies'
import { TZLabel } from 'lib/components/TZLabel'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { getReplayVisionEditDisabledReason } from '../../utils/accessControl'
import { formatCreditCount } from '../../utils/credits'
import { highlightPicksLogic } from '../highlightPicksLogic'
import { highlightPicksStaleLogic } from '../highlightPicksStaleLogic'
import { weeklyVolume } from '../highlightPicksStarter'
import { highlightPicksStarterLogic } from '../highlightPicksStarterLogic'
import { highlightPicksVolumeLogic } from '../highlightPicksVolumeLogic'
import { QuillHighlightPicksStateFrame } from './QuillHighlightPicksStateFrame'
import { QuillHighlightPicksVolumeTiles } from './QuillHighlightPicksVolumeTiles'

const HedgehogNoir = pngHoggie(noirPng)
const SWEEP_STALE_MS = 60 * 60 * 1000

export function QuillHighlightPicksQuietState({ size }: { size: 'small' | 'large' }): JSX.Element {
    const picksLogic = useMountedLogic(highlightPicksLogic)
    const logic = highlightPicksStaleLogic(picksLogic.props)
    const {
        backfillCandidates,
        backfillScannerId,
        backfillEstimate,
        backfillEstimateLoading,
        backfillTotals,
        busyScannerId,
        lastSweptAt,
    } = useValues(logic)
    const { pickBackfillScanner, startBackfill } = useActions(logic)
    const { candidateRecordings } = useValues(highlightPicksStarterLogic(picksLogic.props))
    const { volumeEstimate, volumeEstimateLoading } = useValues(highlightPicksVolumeLogic)
    const large = size === 'large'
    const editDisabledReason = getReplayVisionEditDisabledReason()

    const volume = weeklyVolume(volumeEstimate, candidateRecordings)
    const sweepStale = !!lastSweptAt && Date.now() - new Date(lastSweptAt).getTime() > SWEEP_STALE_MS
    const started = backfillScannerId ? backfillTotals[backfillScannerId] : undefined
    const estimateReady = backfillEstimate?.scannerId === backfillScannerId ? backfillEstimate : null
    const scannerOptions = backfillCandidates.map((scanner) => ({ value: scanner.id, label: scanner.name }))

    return (
        <QuillHighlightPicksStateFrame
            size={size}
            image={HedgehogNoir}
            title="Nothing to watch yet"
            body={
                sweepStale ? (
                    <>
                        {pluralize(backfillCandidates.length, 'scanner')} running, but the last sweep was{' '}
                        <TZLabel time={lastSweptAt} showPopover={false} noStyles />.
                    </>
                ) : (
                    <>
                        {pluralize(backfillCandidates.length, 'scanner')} running
                        {lastSweptAt && (
                            <>
                                , last sweep <TZLabel time={lastSweptAt} showPopover={false} noStyles />
                            </>
                        )}
                        . New recordings are checked regularly and picks appear here.
                    </>
                )
            }
            dataAttr="vision-highlight-picks-quiet"
            footer={
                <Button
                    variant="link"
                    size="inline"
                    className="mt-1"
                    render={<LinkPrimitive to={urls.replayVision()} />}
                    data-attr="vision-highlight-picks-empty-link"
                >
                    Open Replay vision
                </Button>
            }
        >
            <QuillHighlightPicksVolumeTiles
                volume={volume}
                loading={volumeEstimateLoading}
                dataAttr="vision-highlight-picks-quiet-volume"
            />
            {backfillCandidates.length > 0 &&
                (started === undefined ? (
                    <>
                        {backfillCandidates.length > 1 && (
                            <Select
                                items={scannerOptions}
                                value={backfillScannerId}
                                onValueChange={(value: string | null) => pickBackfillScanner(value)}
                            >
                                <SelectTrigger
                                    size="sm"
                                    className="w-full"
                                    data-attr="vision-highlight-picks-quiet-scanner"
                                >
                                    <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                    {scannerOptions.map((option) => (
                                        <SelectItem key={option.value} value={option.value}>
                                            {option.label}
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        )}
                        <Button
                            variant="primary"
                            size={large ? 'default' : 'sm'}
                            className="w-full"
                            loading={busyScannerId === backfillScannerId}
                            disabledReason={
                                editDisabledReason ??
                                (estimateReady && estimateReady.sessions === 0
                                    ? 'No recording in the last 7 days matches this scanner'
                                    : undefined)
                            }
                            onClick={() => backfillScannerId && startBackfill(backfillScannerId)}
                            data-attr="vision-highlight-picks-quiet-backfill"
                        >
                            Scan the last 7 days now
                        </Button>
                        <span className="text-xs">
                            {backfillEstimateLoading
                                ? 'Counting matching recordings'
                                : estimateReady
                                  ? `${pluralize(estimateReady.sessions, 'recording')}, about ${formatCreditCount(estimateReady.credits)}`
                                  : 'Could not count matching recordings'}
                        </span>
                    </>
                ) : started === 0 ? (
                    <span className="text-xs">
                        No recording in the last 7 days matched. New ones are still scanned.
                    </span>
                ) : (
                    <span className="text-xs">
                        Scanning {pluralize(started, 'recording')}. Results land here as they finish.
                    </span>
                ))}
        </QuillHighlightPicksStateFrame>
    )
}
