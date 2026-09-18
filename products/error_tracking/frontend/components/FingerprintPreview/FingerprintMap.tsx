import { ScatterChart, ScatterSeries, TooltipSurface } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { Button, Spinner, Text } from 'lib/ui/quill'

import { FingerprintPointMeta, FingerprintProjectionDomains } from './fingerprintProjectionLogic'

interface FingerprintMapProps {
    domains: FingerprintProjectionDomains | null
    series: ScatterSeries<FingerprintPointMeta>[]
    hasMore?: boolean
    loading: boolean
    error: string | null
    onRetry: () => void
    onSelect: (fingerprint: string) => void
}

export function FingerprintMap({
    domains,
    series,
    hasMore,
    loading,
    error,
    onRetry,
    onSelect,
}: FingerprintMapProps): JSX.Element {
    const theme = useChartTheme()

    if (loading) {
        return (
            <div className="flex min-h-0 flex-1 items-center justify-center">
                <Spinner />
            </div>
        )
    }

    if (error) {
        return (
            <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-2 text-center">
                <Text variant="muted">Couldn't load the fingerprint map.</Text>
                <Button variant="default" size="sm" onClick={onRetry}>
                    Retry
                </Button>
            </div>
        )
    }

    return (
        <>
            <div className="min-h-0 flex-1">
                <ScatterChart
                    series={series}
                    theme={theme}
                    config={{
                        xAxis: { hide: true, domain: domains?.x },
                        yAxis: { hide: true, domain: domains?.y },
                        margins: { top: 8, right: 8, bottom: 8, left: 8 },
                        pointRadius: 5,
                        tooltip: { placement: 'cursor' },
                    }}
                    className="h-full"
                    dataAttr="error-tracking-fingerprint-scatter"
                    tooltip={({ point }) => (
                        <TooltipSurface data-attr="error-tracking-fingerprint-tooltip">{point.label}</TooltipSurface>
                    )}
                    onPointClick={(point) => {
                        if (point.meta?.fingerprint) {
                            onSelect(point.meta.fingerprint)
                        }
                    }}
                />
            </div>
            <Text size="xs" variant="muted" className="pt-1 text-center">
                {hasMore ? 'This map uses a sample of fingerprints. ' : ''}
                Nearby points are similar. Select one to filter exceptions.
            </Text>
        </>
    )
}
