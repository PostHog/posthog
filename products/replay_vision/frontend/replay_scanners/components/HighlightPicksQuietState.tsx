import { useActions, useMountedLogic, useValues } from 'kea'

import * as noirPng from '@posthog/brand/hoggies/png/noir-1'
import { LemonButton, LemonSelect, Link } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { TZLabel } from 'lib/components/TZLabel'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { getReplayVisionEditDisabledReason } from '../../utils/accessControl'
import { formatCreditCount } from '../../utils/credits'
import { highlightPicksLogic } from '../highlightPicksLogic'
import { highlightPicksStaleLogic } from '../highlightPicksStaleLogic'
import { SWEEP_INTERVAL_MINUTES } from '../scannerStatus'
import { HighlightPicksStateFrame } from './HighlightPicksStateFrame'

const HedgehogNoir = pngHoggie(noirPng)

export function HighlightPicksQuietState({ size }: { size: 'small' | 'large' }): JSX.Element {
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
    const large = size === 'large'
    const editDisabledReason = getReplayVisionEditDisabledReason()

    const started = backfillScannerId ? backfillTotals[backfillScannerId] : undefined
    const estimateReady = backfillEstimate?.scannerId === backfillScannerId ? backfillEstimate : null

    return (
        <HighlightPicksStateFrame
            size={size}
            image={HedgehogNoir}
            title="Nothing to watch yet"
            body={
                <>
                    {pluralize(backfillCandidates.length, 'scanner')} running
                    {lastSweptAt && (
                        <>
                            , last sweep <TZLabel time={lastSweptAt} showPopover={false} noStyles />
                        </>
                    )}
                    . New recordings are checked every {SWEEP_INTERVAL_MINUTES} minutes and picks appear here.
                </>
            }
            dataAttr="vision-highlight-picks-quiet"
            footer={
                <Link to={urls.replayVision()} className="mt-1" data-attr="vision-highlight-picks-empty-link">
                    Open Replay vision
                </Link>
            }
        >
            {backfillCandidates.length > 0 &&
                (started === undefined ? (
                    <>
                        {backfillCandidates.length > 1 && (
                            <LemonSelect
                                size="small"
                                fullWidth
                                value={backfillScannerId}
                                onChange={(value) => pickBackfillScanner(value)}
                                options={backfillCandidates.map((scanner) => ({
                                    value: scanner.id,
                                    label: scanner.name,
                                }))}
                                data-attr="vision-highlight-picks-quiet-scanner"
                            />
                        )}
                        <LemonButton
                            type="primary"
                            size={large ? 'medium' : 'small'}
                            fullWidth
                            center
                            loading={busyScannerId === backfillScannerId}
                            disabledReason={
                                editDisabledReason ??
                                (estimateReady && estimateReady.sessions === 0
                                    ? 'No recording in the last 7 days matches this scanner'
                                    : null)
                            }
                            onClick={() => backfillScannerId && startBackfill(backfillScannerId)}
                            data-attr="vision-highlight-picks-quiet-backfill"
                        >
                            Scan the last 7 days now
                        </LemonButton>
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
        </HighlightPicksStateFrame>
    )
}
