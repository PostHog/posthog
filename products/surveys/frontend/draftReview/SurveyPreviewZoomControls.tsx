import { IconMinus, IconPlus } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

const ZOOM_STEP = 1.25

export function SurveyPreviewZoomControls({
    scale,
    fitScale,
    maxScale,
    onZoom,
}: {
    scale: number
    fitScale: number
    maxScale: number
    onZoom: (scale: number | 'fit') => void
}): JSX.Element {
    const isFit = scale === fitScale
    return (
        <div className="flex shrink-0 items-center" data-attr="survey-draft-review-preview-zoom">
            <LemonButton
                size="xsmall"
                icon={<IconMinus />}
                tooltip="Zoom out"
                disabledReason={isFit ? 'The whole page is already in view' : undefined}
                onClick={() => onZoom(scale / ZOOM_STEP)}
            />
            <LemonButton
                size="xsmall"
                tooltip={isFit ? 'Show at actual size' : 'Fit the page to the frame'}
                onClick={() => onZoom(isFit ? 1 : 'fit')}
            >
                <span className="w-9 text-center tabular-nums">{Math.round(scale * 100)}%</span>
            </LemonButton>
            <LemonButton
                size="xsmall"
                icon={<IconPlus />}
                tooltip="Zoom in"
                disabledReason={scale >= maxScale ? 'Zoomed in as far as it goes' : undefined}
                onClick={() => onZoom(scale * ZOOM_STEP)}
            />
        </div>
    )
}
