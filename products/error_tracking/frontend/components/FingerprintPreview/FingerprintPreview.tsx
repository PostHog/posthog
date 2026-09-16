import { useActions, useValues } from 'kea'

import { ScatterChart, TooltipSurface } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { Button, Spinner, Text } from 'lib/ui/quill'

import { PropertyOperator } from '~/types'

import { IssueFilterPreviewHeader } from '../IssueFilterPreview/IssueFilterPreviewHeader'
import { issueFilterPreviewLogic } from '../IssueFilterPreview/issueFilterPreviewLogic'
import { fingerprintProjectionLogic } from './fingerprintProjectionLogic'

export function FingerprintPreview({ issueId }: { issueId: string }): JSX.Element {
    const { fingerprintDomains, fingerprintSeries, projection, projectionError, projectionLoading } = useValues(
        fingerprintProjectionLogic({ issueId })
    )
    const { loadProjection } = useActions(fingerprintProjectionLogic({ issueId }))
    const { applyPropertyFilter } = useActions(issueFilterPreviewLogic)
    const theme = useChartTheme()

    return (
        <div className="flex flex-col">
            <IssueFilterPreviewHeader preview="fingerprints" title="Fingerprints" />
            <div className="flex h-64 min-h-0 flex-col px-3 pb-3 pt-2">
                {projectionLoading ? (
                    <div className="flex min-h-0 flex-1 items-center justify-center">
                        <Spinner />
                    </div>
                ) : projectionError ? (
                    <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-2 text-center">
                        <Text variant="muted">Couldn't load the fingerprint map.</Text>
                        <Button
                            variant="default"
                            size="sm"
                            loading={projectionLoading}
                            onClick={() => loadProjection()}
                        >
                            Retry
                        </Button>
                    </div>
                ) : projection.results.length === 0 ? (
                    <div className="flex min-h-0 flex-1 items-center justify-center text-center">
                        <Text variant="muted">No fingerprint embeddings available yet.</Text>
                    </div>
                ) : (
                    <>
                        <div className="min-h-0 flex-1">
                            <ScatterChart
                                series={fingerprintSeries}
                                theme={theme}
                                config={{
                                    xAxis: { hide: true, domain: fingerprintDomains?.x },
                                    yAxis: { hide: true, domain: fingerprintDomains?.y },
                                    margins: { top: 8, right: 8, bottom: 8, left: 8 },
                                    pointRadius: 5,
                                    tooltip: { placement: 'cursor' },
                                }}
                                className="h-full"
                                dataAttr="error-tracking-fingerprint-scatter"
                                tooltip={({ point }) => (
                                    <TooltipSurface data-attr="error-tracking-fingerprint-tooltip">
                                        {point.label}
                                    </TooltipSurface>
                                )}
                                onPointClick={(point) => {
                                    if (point.meta?.fingerprint) {
                                        applyPropertyFilter(
                                            '$exception_fingerprint',
                                            point.meta.fingerprint,
                                            PropertyOperator.Exact,
                                            true
                                        )
                                    }
                                }}
                            />
                        </div>
                        <Text size="xs" variant="muted" className="pt-1 text-center">
                            {projection.hasMore ? 'This map uses a sample of fingerprints. ' : ''}
                            Nearby points are similar. Select one to filter exceptions.
                        </Text>
                    </>
                )}
            </div>
        </div>
    )
}
