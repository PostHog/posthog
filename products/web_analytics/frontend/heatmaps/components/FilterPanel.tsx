import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconGear } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { HEATMAP_LOADING_DEBOUNCE_MS, heatmapDataLogic } from 'lib/components/heatmaps/heatmapDataLogic'
import { HeatmapsSettings } from 'lib/components/heatmaps/HeatMapsSettings'
import { useDebouncedValue } from 'lib/hooks/useDebouncedValue'
import { LoadingBar } from 'lib/lemon-ui/LoadingBar'
import { Popover } from 'lib/lemon-ui/Popover'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

import { HeatmapFilterControls } from './HeatmapFilterControls'

/**
 * values and actions are passed as props because they are different
 * between fixed and embedded mode
 */
export function FilterPanel({
    clickmapSettings,
    lockedWidth,
    previewUnavailable = false,
}: {
    previewUnavailable?: boolean
    clickmapSettings?: JSX.Element
    lockedWidth?: number
}): JSX.Element {
    const [isSettingsOpen, setIsSettingsOpen] = useState(false)
    const {
        heatmapFilters,
        heatmapColorPalette,
        heatmapFixedPositionMode,
        viewportRange,
        rawHeatmapLoading,
        heatmapEmpty,
    } = useValues(heatmapDataLogic({ context: 'in-app' }))
    const { patchHeatmapFilters, setHeatmapColorPalette, setHeatmapFixedPositionMode } = useActions(
        heatmapDataLogic({ context: 'in-app' })
    )

    const debouncedLoading = useDebouncedValue(rawHeatmapLoading, HEATMAP_LOADING_DEBOUNCE_MS)

    // KLUDGE: the loading bar flaps in visual regression tests,
    // for some reason our wait for loading to finish can't see it
    // this is ugly but better than stopping taking visual snapshots of it
    return (
        <div className="relative">
            {debouncedLoading && !inStorybook() && !inStorybookTestRunner() && (
                <LoadingBar
                    wrapperClassName="absolute top-0 left-0 w-full overflow-hidden rounded-none my-0"
                    className="h-1 rounded-none"
                />
            )}
            <HeatmapFilterControls
                lockedWidth={lockedWidth}
                settings={
                    <>
                        <div className="min-w-0">
                            <Popover
                                overlay={
                                    <div className="p-2 w-80 max-h-96 overflow-y-auto">
                                        <HeatmapsSettings
                                            heatmapFilters={heatmapFilters}
                                            patchHeatmapFilters={patchHeatmapFilters}
                                            viewportRange={viewportRange}
                                            heatmapColorPalette={heatmapColorPalette}
                                            setHeatmapColorPalette={setHeatmapColorPalette}
                                            heatmapFixedPositionMode={heatmapFixedPositionMode}
                                            setHeatmapFixedPositionMode={setHeatmapFixedPositionMode}
                                        />
                                    </div>
                                }
                                visible={isSettingsOpen}
                                onClickOutside={() => {
                                    setIsSettingsOpen(false)
                                }}
                                placement="bottom"
                            >
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    onClick={() => setIsSettingsOpen(!isSettingsOpen)}
                                    icon={<IconGear />}
                                    tooltip="Heatmap settings"
                                    data-attr="heatmap-settings"
                                >
                                    Heatmap settings
                                </LemonButton>
                            </Popover>
                        </div>
                        {clickmapSettings ? <div className="min-w-0">{clickmapSettings}</div> : null}
                    </>
                }
                drawerFooter={
                    <p className="text-xs text-muted basis-full mb-0">
                        Viewing filters and screen width aren't saved with this heatmap.
                    </p>
                }
            />
            {heatmapEmpty && !rawHeatmapLoading && !previewUnavailable ? (
                <p className="text-sm text-muted mt-2 mb-0">
                    No interactions found. Try a different date range or adjust your filters.
                </p>
            ) : null}
        </div>
    )
}
