import { LemonBanner } from '@posthog/lemon-ui'

import { useQuillSurface } from 'lib/components/QuillSurface/quillSurfaceContext'

import { QuillInsightBanner } from 'products/product_analytics/frontend/insights/shared/QuillInsightBanner'

export function ExplainChartOutdatedNotice({ explainAvailable }: { explainAvailable: boolean }): JSX.Element {
    const quillSurface = useQuillSurface()
    const message = explainAvailable
        ? "The explanation is hidden because your changes affect the chart's data. Undo them to see it again, or save and explain this version."
        : "The explanation is hidden because your changes affect the chart's data. Undo them to see it again."

    if (quillSurface) {
        return (
            <QuillInsightBanner tone="info" className="m-2 w-auto">
                {message}
            </QuillInsightBanner>
        )
    }

    return (
        <LemonBanner type="info" className="m-2">
            {message}
        </LemonBanner>
    )
}
