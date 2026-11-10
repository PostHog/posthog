import { useActions, useValues } from 'kea'
import { useId, useState } from 'react'

import { IconInfo } from '@posthog/icons'
import { LemonInput, LemonSwitch } from '@posthog/lemon-ui'
import { Field, FieldTitle, Input, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { QuillChartOptionLabel } from 'lib/components/ChartOptions/QuillChartOptionLabel'
import { QuillChartOptionSwitch } from 'lib/components/ChartOptions/QuillChartOptionSwitch'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { useQuillSurface } from 'lib/components/QuillSurface/quillSurfaceContext'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { AvailableFeature, EditorFilterProps, PathEdgeParameters } from '~/types'

import { pathsDataLogic } from 'products/product_analytics/frontend/insights/paths/pathsDataLogic'

import { PathCleaningFilter } from '../filters/PathCleaningFilter'

const SHOW_FULL_URLS_INFO =
    'Display complete URLs instead of truncated versions. Useful for comparing paths side-by-side.'
const EDGE_LIMIT_INFO =
    'Determines the maximum number of path nodes that can be generated. If necessary certain items will be grouped.'
const EDGE_WEIGHT_INFO =
    'Determines the minimum and maximum number of persons in each path. Helps adjust the density of the visualization.'
const PATH_CLEANING_INFO =
    'Cleaning rules are an advanced feature that uses regex to normalize URLS for paths visualization. Rules can be set for all insights in the project settings, or they can be defined specifically for an insight.'
const STRIP_QUERY_STRING_INFO =
    'Treat page views that differ only in the query string as the same step. For example, /products?color=red and /products both count as /products.'

export function PathsAdvanced({ insightProps, ...rest }: EditorFilterProps): JSX.Element {
    const { pathsFilter } = useValues(pathsDataLogic(insightProps))
    const { updateInsightFilter } = useActions(pathsDataLogic(insightProps))

    const { featureFlags } = useValues(featureFlagLogic)
    const quillSurface = useQuillSurface()
    const edgeLimitId = useId()
    const minEdgeWeightId = useId()

    const { edgeLimit, minEdgeWeight, maxEdgeWeight, showFullUrls, stripQueryString } = pathsFilter || {}

    const [localEdgeParameters, setLocalEdgeParameters] = useState<PathEdgeParameters>({
        edgeLimit,
        minEdgeWeight,
        maxEdgeWeight,
    })

    const updateEdgeParameters = (): void => {
        if (
            localEdgeParameters.edgeLimit !== edgeLimit ||
            localEdgeParameters.minEdgeWeight !== minEdgeWeight ||
            localEdgeParameters.maxEdgeWeight !== maxEdgeWeight
        ) {
            updateInsightFilter({ ...localEdgeParameters })
        }
    }

    const onEdgeLimitChange = (value: number | undefined): void =>
        setLocalEdgeParameters((state) => ({
            ...state,
            edgeLimit: Number(value),
        }))
    const onMinEdgeWeightChange = (value: number | undefined): void => {
        setLocalEdgeParameters((state) => ({
            ...state,
            minEdgeWeight: Number(value),
        }))
        updateEdgeParameters()
    }
    const onMaxEdgeWeightChange = (value: number | undefined): void => {
        setLocalEdgeParameters((state) => ({
            ...state,
            maxEdgeWeight: Number(value),
        }))
        updateEdgeParameters()
    }
    const commitOnEnter = (event: React.KeyboardEvent<HTMLInputElement>): void => {
        if (event.key === 'Enter') {
            updateEdgeParameters()
        }
    }

    return (
        <div className="flex flex-col gap-4">
            <PayGateMini feature={AvailableFeature.PATHS_ADVANCED} featureDetail="paths-advanced-filter">
                {quillSurface ? (
                    <div className="flex flex-col gap-4">
                        <Field>
                            <QuillChartOptionLabel
                                htmlFor={edgeLimitId}
                                label="Maximum number of paths"
                                info={EDGE_LIMIT_INFO}
                            />
                            <Input
                                id={edgeLimitId}
                                type="number"
                                min={0}
                                max={1000}
                                defaultValue={localEdgeParameters.edgeLimit || 50}
                                onChange={(event) => onEdgeLimitChange(event.currentTarget.valueAsNumber)}
                                onBlur={updateEdgeParameters}
                                onKeyDown={commitOnEnter}
                            />
                        </Field>
                        <Field>
                            <QuillChartOptionLabel
                                htmlFor={minEdgeWeightId}
                                label="Number of people on each path"
                                info={EDGE_WEIGHT_INFO}
                            />
                            <div className="flex flex-wrap items-center gap-2">
                                <span>Between</span>
                                <Input
                                    id={minEdgeWeightId}
                                    type="number"
                                    className="w-24"
                                    min={0}
                                    max={100000}
                                    defaultValue={localEdgeParameters.minEdgeWeight}
                                    onChange={(event) => onMinEdgeWeightChange(event.currentTarget.valueAsNumber)}
                                    onBlur={updateEdgeParameters}
                                    onKeyDown={commitOnEnter}
                                />
                                <span>and</span>
                                <Input
                                    type="number"
                                    className="w-24"
                                    aria-label="Maximum number of people on each path"
                                    min={0}
                                    max={100000}
                                    defaultValue={localEdgeParameters.maxEdgeWeight}
                                    onChange={(event) => onMaxEdgeWeightChange(event.currentTarget.valueAsNumber)}
                                    onBlur={updateEdgeParameters}
                                    onKeyDown={commitOnEnter}
                                />
                                <span>persons.</span>
                            </div>
                        </Field>
                        <Field>
                            <FieldTitle className="items-center gap-1 font-normal">
                                Path Cleaning Rules
                                <Tooltip>
                                    <TooltipTrigger
                                        render={<span className="inline-flex text-muted-foreground" />}
                                        aria-label="More info"
                                    >
                                        <IconInfo />
                                    </TooltipTrigger>
                                    <TooltipContent>{PATH_CLEANING_INFO}</TooltipContent>
                                </Tooltip>
                            </FieldTitle>
                            <PathCleaningFilter insightProps={insightProps} {...rest} />
                        </Field>
                    </div>
                ) : (
                    <>
                        <div className="flex flex-col gap-2">
                            <LemonLabel info={EDGE_LIMIT_INFO}>Maximum number of paths</LemonLabel>
                            <LemonInput
                                type="number"
                                min={0}
                                max={1000}
                                defaultValue={localEdgeParameters.edgeLimit || 50}
                                onChange={onEdgeLimitChange}
                                onBlur={updateEdgeParameters}
                                onPressEnter={updateEdgeParameters}
                            />

                            <LemonLabel info={EDGE_WEIGHT_INFO} className="mt-2">
                                Number of people on each path
                            </LemonLabel>
                        </div>
                        <div className="flex items-baseline">
                            <span className="mr-2">Between</span>
                            <LemonInput
                                type="number"
                                min={0}
                                max={100000}
                                defaultValue={localEdgeParameters.minEdgeWeight}
                                onChange={onMinEdgeWeightChange}
                                onBlur={updateEdgeParameters}
                                onPressEnter={updateEdgeParameters}
                            />
                            <span className="mx-2">and</span>
                            <LemonInput
                                type="number"
                                onChange={onMaxEdgeWeightChange}
                                min={0}
                                max={100000}
                                defaultValue={localEdgeParameters.maxEdgeWeight}
                                onBlur={updateEdgeParameters}
                                onPressEnter={updateEdgeParameters}
                            />
                            <span className="ml-2">persons.</span>
                        </div>

                        <div>
                            <div className="flex items-center my-2">
                                <LemonLabel info={<>{PATH_CLEANING_INFO}</>}>Path Cleaning Rules</LemonLabel>
                            </div>
                            <PathCleaningFilter insightProps={insightProps} {...rest} />
                        </div>
                    </>
                )}
            </PayGateMini>

            {/* Show full URLs toggle - outside paywall */}
            {quillSurface ? (
                <QuillChartOptionSwitch
                    label="Show full URLs"
                    info={SHOW_FULL_URLS_INFO}
                    checked={!!showFullUrls}
                    onChange={(checked) => updateInsightFilter({ showFullUrls: checked })}
                />
            ) : (
                <div>
                    <LemonSwitch
                        checked={!!showFullUrls}
                        onChange={(checked) => updateInsightFilter({ showFullUrls: checked })}
                        label="Show full URLs"
                        bordered
                        fullWidth
                    />
                    <div className="text-muted text-xs mt-1">{SHOW_FULL_URLS_INFO}</div>
                </div>
            )}

            {(featureFlags[FEATURE_FLAGS.PRODUCT_ANALYTICS_PATHS_STRIP_QUERY_STRING] || stripQueryString) &&
                (quillSurface ? (
                    <QuillChartOptionSwitch
                        label="Ignore URL query strings"
                        info={STRIP_QUERY_STRING_INFO}
                        checked={!!stripQueryString}
                        onChange={(checked) => updateInsightFilter({ stripQueryString: checked })}
                    />
                ) : (
                    <div>
                        <LemonSwitch
                            checked={!!stripQueryString}
                            onChange={(checked) => updateInsightFilter({ stripQueryString: checked })}
                            label="Ignore URL query strings"
                            bordered
                            fullWidth
                        />
                        <div className="text-muted text-xs mt-1">{STRIP_QUERY_STRING_INFO}</div>
                    </div>
                ))}
        </div>
    )
}
