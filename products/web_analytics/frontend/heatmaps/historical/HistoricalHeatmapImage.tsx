import clsx from 'clsx'
import { useEffect, useRef, useState } from 'react'

import { LemonBanner, Tooltip } from '@posthog/lemon-ui'

import { createHeatmapRenderer } from 'lib/components/heatmaps/heatmapRenderer'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { pluralize } from 'lib/utils/strings'

import type { HeatmapAnalysisVariantApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { HISTORICAL_HEATMAP_RADIUS, countHistoricalHeatmapClicks } from './countHistoricalHeatmapClicks'

export function HistoricalHeatmapImage({
    variant,
    backgroundUrl,
    maxHeight,
    overlayClassName,
}: {
    variant: HeatmapAnalysisVariantApi
    backgroundUrl: string
    maxHeight?: number
    overlayClassName?: string
}): JSX.Element {
    const overlayRef = useRef<HTMLDivElement | null>(null)
    const { ref, width } = useResizeObserver()
    const [imageState, setImageState] = useState<'loading' | 'ready' | 'error'>('loading')
    const [hoverPosition, setHoverPosition] = useState<{ x: number; y: number } | null>(null)
    const scale = Math.min(1, (width || variant.width) / variant.width)
    const visibleHeight = Math.min(variant.height, maxHeight ?? variant.height)
    const hoveredClicks = hoverPosition ? countHistoricalHeatmapClicks(variant.clicks, hoverPosition, scale) : 0
    useEffect(() => {
        setHoverPosition(null)
    }, [scale])
    const hovering = hoverPosition !== null
    useEffect(() => {
        if (!hovering) {
            return
        }
        const clearHover = (): void => setHoverPosition(null)
        window.addEventListener('scroll', clearHover, true)
        window.addEventListener('keydown', clearHover)
        return () => {
            window.removeEventListener('scroll', clearHover, true)
            window.removeEventListener('keydown', clearHover)
        }
    }, [hovering])
    useEffect(() => {
        const container = overlayRef.current
        if (!container || imageState !== 'ready') {
            return
        }
        const heatmap = createHeatmapRenderer(container, { radius: HISTORICAL_HEATMAP_RADIUS * scale })
        heatmap.setData({
            max: Math.max(1, ...variant.clicks.map((click) => click.count)),
            min: 0,
            data: variant.clicks
                .filter((click) => click.y <= visibleHeight)
                .map((click) => ({
                    x: Math.round(click.x * scale),
                    y: Math.round(click.y * scale),
                    value: click.count,
                })),
        })
        return () => {
            container.replaceChildren()
        }
    }, [variant, scale, imageState, visibleHeight])
    return (
        <div ref={ref} className="w-full overflow-hidden">
            {imageState === 'error' ? (
                <LemonBanner type="warning">
                    This screenshot is unavailable. Choose another recorded moment or refresh results.
                </LemonBanner>
            ) : (
                <div
                    className="relative mx-auto overflow-hidden"
                    style={{ width: variant.width * scale, height: visibleHeight * scale }}
                    onPointerMove={(event) => {
                        if (imageState === 'ready') {
                            const bounds = event.currentTarget.getBoundingClientRect()
                            setHoverPosition({ x: event.clientX - bounds.left, y: event.clientY - bounds.top })
                        }
                    }}
                    onPointerLeave={() => setHoverPosition(null)}
                    onPointerDown={() => setHoverPosition(null)}
                >
                    <img
                        loading="lazy"
                        src={backgroundUrl}
                        alt="Reconstructed historical page"
                        className="block w-full"
                        onLoad={() => setImageState('ready')}
                        onError={() => setImageState('error')}
                    />
                    {imageState === 'ready' && (
                        <div
                            className={clsx('absolute inset-0 pointer-events-none', overlayClassName)}
                            data-attr="historical-heatmap-click-overlay"
                        >
                            <div ref={overlayRef} className="w-full h-full" />
                        </div>
                    )}
                    {imageState === 'ready' && hoverPosition && hoveredClicks > 0 && (
                        <Tooltip
                            title={`${hoveredClicks.toLocaleString()} ${pluralize(hoveredClicks, 'click', undefined, false)} in this area`}
                            visible
                            placement="top"
                            containerClassName="pointer-events-none"
                        >
                            <span
                                className="absolute size-px pointer-events-none"
                                style={{ left: hoverPosition.x, top: hoverPosition.y }}
                            />
                        </Tooltip>
                    )}
                </div>
            )}
        </div>
    )
}
