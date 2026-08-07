import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconGear, IconLaptop, IconPhone, IconTabletLandscape, IconTabletPortrait } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSegmentedButton, LemonSelect } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { heatmapDataLogic } from 'lib/components/heatmaps/heatmapDataLogic'
import { HeatmapsSettings } from 'lib/components/heatmaps/HeatMapsSettings'
import { SectionSetting } from 'lib/components/heatmaps/HeatMapsSettings'
import { heatmapDateOptions } from 'lib/components/IframedToolbarBrowser/utils'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LoadingBar } from 'lib/lemon-ui/LoadingBar'
import { Popover } from 'lib/lemon-ui/Popover'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'
import { COHORTS_ONLY_SUPPORT_IN_PICKER_PROPS } from 'scenes/feature-flags/cohortPickerProps'
import { TestAccountFilter } from 'scenes/insights/filters/TestAccountFilter'

import { AnyPropertyFilter, CohortPropertyFilter, HeatmapType, PropertyFilterType, PropertyOperator } from '~/types'

import { buildQueryAgnosticUrlPattern } from './heatmapsBrowserLogic'

const cohortIdsToPropertyFilters = (ids: number[]): AnyPropertyFilter[] =>
    ids.map((id) => ({
        type: PropertyFilterType.Cohort,
        key: 'id',
        value: id,
        operator: PropertyOperator.In,
    }))

const propertyFiltersToCohortIds = (filters: AnyPropertyFilter[]): number[] =>
    filters
        .filter((f): f is CohortPropertyFilter => f.type === PropertyFilterType.Cohort)
        .map((f) => f.value)
        .filter((v): v is number => typeof v === 'number')

const useDebounceLoading = (loading: boolean, delay = 200): boolean => {
    const [debouncedLoading, setDebouncedLoading] = useState(false)

    useEffect(() => {
        const timer = setTimeout(() => {
            setDebouncedLoading(loading)
        }, delay)

        return () => clearTimeout(timer)
    }, [loading, delay])

    return debouncedLoading
}

export function ViewportChooser(): JSX.Element {
    const { widthOverride } = useValues(heatmapDataLogic({ context: 'in-app' }))
    const { setWindowWidthOverride } = useActions(heatmapDataLogic({ context: 'in-app' }))

    const options = [
        {
            value: 320,
            icon: <IconPhone />,
        },
        {
            value: 375,
            icon: <IconPhone />,
        },
        {
            value: 425,
            icon: <IconPhone />,
        },
        {
            value: 768,
            icon: <IconTabletPortrait />,
        },
        {
            value: 1024,
            icon: <IconTabletLandscape />,
        },
        {
            value: 1440,
            icon: <IconLaptop />,
        },
        {
            value: 1920,
            icon: <IconLaptop />,
        },
    ]

    // Let's add current width as an option if it's not in the list
    const allOptions = [...options]
    if (widthOverride && !options.some((option) => option.value === widthOverride)) {
        allOptions.push({
            value: widthOverride,
            icon: <IconLaptop />,
        })
    }

    return (
        <div className="flex justify-center items-center gap-2">
            <span>Screen width:</span>
            <LemonSelect
                size="small"
                onChange={setWindowWidthOverride}
                value={widthOverride}
                data-attr="viewport-chooser"
                options={allOptions.map(({ value, icon }) => ({
                    value,
                    label: (
                        <div className="flex items-center gap-1">
                            {icon}
                            <div className="text-xs">{value} px</div>
                        </div>
                    ),
                }))}
            />
        </div>
    )
}

/**
 * values and actions are passed as props because they are different
 * between fixed and embedded mode
 */
export function FilterPanel({
    captureMethod,
    onCaptureMethodChange,
    clickmapSettings,
}: {
    captureMethod?: HeatmapType
    onCaptureMethodChange?: (type: HeatmapType) => void
    clickmapSettings?: JSX.Element
}): JSX.Element {
    const [isSettingsOpen, setIsSettingsOpen] = useState(false)
    const {
        heatmapFilters,
        heatmapColorPalette,
        heatmapFixedPositionMode,
        viewportRange,
        commonFilters,
        rawHeatmapLoading,
    } = useValues(heatmapDataLogic({ context: 'in-app' }))

    const { patchHeatmapFilters, setHeatmapColorPalette, setHeatmapFixedPositionMode, setCommonFilters } = useActions(
        heatmapDataLogic({ context: 'in-app' })
    )

    const cohortFilterEnabled = useFeatureFlag('HEATMAPS_COHORT_FILTER')

    const debouncedLoading = useDebounceLoading(rawHeatmapLoading ?? false)

    // KLUDGE: the loading bar flaps in visual regression tests,
    // for some reason our wait for loading to finish can't see it
    // this is ugly but better than stopping taking visual snapshots of it
    return (
        <>
            {debouncedLoading && !inStorybook() && !inStorybookTestRunner() && (
                <LoadingBar
                    wrapperClassName="absolute top-0 left-0 w-full overflow-hidden rounded-none my-0"
                    className="h-1 rounded-none"
                />
            )}
            <div className="flex-none md:flex justify-between items-center gap-2 my-2">
                <div className="flex-none md:flex items-center gap-2 my-2 md:my-0">
                    <DateFilter
                        dateFrom={commonFilters?.date_from}
                        dateTo={commonFilters?.date_to}
                        onChange={(fromDate, toDate) => {
                            setCommonFilters?.({ ...commonFilters, date_from: fromDate, date_to: toDate })
                        }}
                        dateOptions={heatmapDateOptions}
                    />
                    {cohortFilterEnabled && (
                        <div className="mt-2 md:mt-0">
                            <PropertyFilters
                                pageKey="heatmap-cohorts"
                                propertyFilters={cohortIdsToPropertyFilters(commonFilters?.cohort_ids ?? [])}
                                onChange={(filters) =>
                                    setCommonFilters?.({
                                        ...commonFilters,
                                        cohort_ids: propertyFiltersToCohortIds(filters),
                                    })
                                }
                                taxonomicGroupTypes={[TaxonomicFilterGroupType.Cohorts]}
                                buttonText="Filter by cohort"
                                addText="Add cohort filter"
                                buttonSize="small"
                                {...COHORTS_ONLY_SUPPORT_IN_PICKER_PROPS}
                            />
                        </div>
                    )}
                    <div className="mt-2 md:mt-0">
                        <Popover
                            overlay={
                                <div className="p-2 w-80">
                                    <HeatmapsSettings
                                        heatmapFilters={heatmapFilters}
                                        patchHeatmapFilters={patchHeatmapFilters}
                                        viewportRange={viewportRange}
                                        heatmapColorPalette={heatmapColorPalette}
                                        setHeatmapColorPalette={setHeatmapColorPalette}
                                        heatmapFixedPositionMode={heatmapFixedPositionMode}
                                        setHeatmapFixedPositionMode={setHeatmapFixedPositionMode}
                                    />
                                    {captureMethod && onCaptureMethodChange && (
                                        <SectionSetting
                                            title="Capture method"
                                            info="Screenshot generates a full-page screenshot. Iframe loads your site directly."
                                        >
                                            <LemonSegmentedButton
                                                onChange={onCaptureMethodChange}
                                                value={captureMethod}
                                                options={[
                                                    {
                                                        value: 'screenshot',
                                                        label: 'Screenshot',
                                                    },
                                                    {
                                                        value: 'iframe',
                                                        label: 'Iframe',
                                                    },
                                                ]}
                                                size="small"
                                            />
                                        </SectionSetting>
                                    )}
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
                    {clickmapSettings ? <div className="mt-2 md:mt-0">{clickmapSettings}</div> : null}
                    <div className="mt-2 md:mt-0">
                        <TestAccountFilter
                            size="small"
                            filters={{ filter_test_accounts: commonFilters?.filter_test_accounts }}
                            onChange={(value) => {
                                setCommonFilters?.({
                                    ...commonFilters,
                                    filter_test_accounts: value.filter_test_accounts,
                                })
                            }}
                        />
                    </div>
                </div>
                <ViewportChooser />
            </div>
            <LowDataHint />
        </>
    )
}

/**
 * When a heatmap comes back empty or with only a handful of interactions, name the two filters
 * that most often hide data on a busy page (exact-URL matching and the viewport width band) and
 * give a one-click way to loosen each, instead of leaving the page looking dead.
 */
function LowDataHint(): JSX.Element | null {
    const { heatmapEmpty, heatmapSparse, heatmapInteractionCount, href, heatmapFilters, viewportRange } = useValues(
        heatmapDataLogic({ context: 'in-app' })
    )
    const { setHref, setHrefMatchType, patchHeatmapFilters } = useActions(heatmapDataLogic({ context: 'in-app' }))

    if (!heatmapEmpty && !heatmapSparse) {
        return null
    }

    // Offer to drop the query string whenever the matched URL carries one, so query-string variants
    // of the page stop being counted as separate pages. This is independent of hrefMatchType: a URL
    // with a "?" is classified as a pattern, but still only matches its own query string.
    const queryAgnosticPattern = href ? buildQueryAgnosticUrlPattern(href) : null
    const canDropQueryString = !!queryAgnosticPattern && href !== queryAgnosticPattern
    const viewportRestrictive = (heatmapFilters?.viewportAccuracy ?? 0) > 0

    const intro = heatmapEmpty
        ? 'No interactions match these filters.'
        : `Only ${heatmapInteractionCount} ${
              heatmapInteractionCount === 1 ? 'interaction matches' : 'interactions match'
          } these filters.`

    return (
        <LemonBanner type="info" className="mb-2">
            <p className="mb-1 font-semibold">{intro}</p>
            <p className="mb-1">
                On pages that get a lot of traffic, this usually means a filter is narrowing the data:
            </p>
            <ul className="list-disc pl-4 deprecated-space-y-2">
                {canDropQueryString ? (
                    <li>
                        <span>
                            This URL includes a query string (like <code>?utm_source=…</code>), and each variant of it
                            is counted as a separate page.
                        </span>
                        <div className="mt-1">
                            <LemonButton
                                type="secondary"
                                size="xsmall"
                                onClick={() => {
                                    setHrefMatchType('pattern')
                                    setHref(queryAgnosticPattern as string)
                                }}
                            >
                                Match any query string
                            </LemonButton>
                        </div>
                    </li>
                ) : null}
                <li>
                    <span>
                        Only viewports from {viewportRange?.min}px to {viewportRange?.max}px are counted, based on your
                        screen width, so visitors on other screen sizes are left out.
                    </span>
                    {viewportRestrictive ? (
                        <div className="mt-1">
                            <LemonButton
                                type="secondary"
                                size="xsmall"
                                onClick={() => patchHeatmapFilters?.({ viewportAccuracy: 0 })}
                            >
                                Include all screen widths
                            </LemonButton>
                        </div>
                    ) : null}
                </li>
            </ul>
            <p className="mt-1 mb-0">You can also widen the date range above.</p>
        </LemonBanner>
    )
}
