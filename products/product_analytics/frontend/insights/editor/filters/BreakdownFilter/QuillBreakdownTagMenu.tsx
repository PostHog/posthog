import { useActions, useValues } from 'kea'
import { useId, useState } from 'react'

import { IconGear } from '@posthog/icons'
import { Button, Input, Label, RadioGroup, RadioGroupItem, Separator, Text } from '@posthog/quill'

import { QuillChartOptionSwitch } from 'lib/components/ChartOptions/QuillChartOptionSwitch'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { breakdownTagLogic } from './breakdownTagLogic'
import { GlobalBreakdownOptionsMenu } from './GlobalBreakdownOptionsMenu'
import { taxonomicBreakdownFilterLogic } from './taxonomicBreakdownFilterLogic'

const USE_BINS = 'bins'
const NO_BINS = 'none'

export function QuillBreakdownTagMenu(): JSX.Element {
    const id = useId()
    const {
        isHistogramable,
        isNormalizeable,
        histogramBinCount,
        normalizeBreakdownURL,
        histogramBinsUsed,
        pathCleaningEnabled,
        hasAdvancedPaths,
        hasPathCleaningFilters,
    } = useValues(breakdownTagLogic)
    const {
        removeBreakdown,
        setHistogramBinCount,
        setHistogramBinsUsed,
        setNormalizeBreakdownURL,
        setPathCleaningEnabled,
    } = useActions(breakdownTagLogic)
    const { isMultipleBreakdownsEnabled } = useValues(taxonomicBreakdownFilterLogic)
    const [binCountDraft, setBinCountDraft] = useState<string | null>(null)

    return (
        <>
            {isNormalizeable && (
                <QuillChartOptionSwitch
                    label="Normalize paths"
                    info='Strip noise (trailing slashes, question marks, and hashes) from paths by enabling this option. Without path normalization, "https://example.com", "https://example.com/", "https://example.com/?" and "https://example.com/#" are treated as four distinct breakdown values. With normalization, they all count towards "https://example.com".'
                    checked={normalizeBreakdownURL}
                    onChange={setNormalizeBreakdownURL}
                />
            )}
            {isNormalizeable && hasAdvancedPaths && (
                <div className="flex flex-col gap-1">
                    <QuillChartOptionSwitch
                        label="Path cleaning"
                        info="Apply your team's path cleaning rules to standardize URLs by removing unnecessary parameters and fragments."
                        checked={hasPathCleaningFilters ? pathCleaningEnabled : false}
                        onChange={setPathCleaningEnabled}
                        disabledReason={
                            hasPathCleaningFilters ? undefined : "You don't have any path cleaning filters configured."
                        }
                    />
                    <Button
                        variant="link-muted"
                        size="sm"
                        className="self-start"
                        render={
                            <LinkPrimitive
                                to={urls.settings('project-product-analytics', 'path-cleaning')}
                                target="_blank"
                            />
                        }
                    >
                        <IconGear />
                        {hasPathCleaningFilters ? 'Edit path cleaning settings' : 'Configure path cleaning'}
                    </Button>
                </div>
            )}
            {isHistogramable ? (
                <RadioGroup
                    value={histogramBinsUsed ? USE_BINS : NO_BINS}
                    onValueChange={(next) => setHistogramBinsUsed(next === USE_BINS)}
                    className="gap-2"
                >
                    <div className="flex items-center gap-2">
                        <RadioGroupItem value={USE_BINS} id={`${id}-bins`} />
                        <Label htmlFor={`${id}-bins`} className="font-normal">
                            Use
                        </Label>
                        <Input
                            type="number"
                            min={1}
                            size="sm"
                            className="w-16"
                            aria-label="Number of bins"
                            value={binCountDraft ?? histogramBinCount ?? ''}
                            onFocus={() => !histogramBinsUsed && setHistogramBinsUsed(true)}
                            onChange={(event) => {
                                setBinCountDraft(event.target.value)
                                const count = event.target.valueAsNumber
                                if (!Number.isNaN(count)) {
                                    setHistogramBinCount(count)
                                }
                            }}
                            onBlur={() => setBinCountDraft(null)}
                        />
                        <Text size="xs" render={<span />}>
                            bins
                        </Text>
                    </div>
                    <div className="flex items-center gap-2">
                        <RadioGroupItem value={NO_BINS} id={`${id}-no-bins`} />
                        <Label htmlFor={`${id}-no-bins`} className="font-normal">
                            Do not bin numeric values
                        </Label>
                    </div>
                </RadioGroup>
            ) : (
                !isMultipleBreakdownsEnabled && <GlobalBreakdownOptionsMenu />
            )}
            <Separator />
            <Button variant="destructive-outline" className="w-full" onClick={removeBreakdown}>
                Remove breakdown
            </Button>
        </>
    )
}
