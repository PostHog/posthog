import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconInfo } from '@posthog/icons'
import {
    Field,
    FieldDescription,
    FieldLabel,
    Input,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { QuillLabeledSwitch } from 'lib/components/QuillLabeledSwitch/QuillLabeledSwitch'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { AvailableFeature, EditorFilterProps, PathEdgeParameters } from '~/types'

import { pathsDataLogic } from 'products/product_analytics/frontend/insights/paths/pathsDataLogic'

import { PathCleaningFilter } from '../filters/PathCleaningFilter'

function InfoTooltip({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <Tooltip>
            <TooltipTrigger render={<span className="inline-flex" tabIndex={0} aria-label="More info" />}>
                <IconInfo className="size-4 text-muted-foreground" />
            </TooltipTrigger>
            <TooltipContent className="max-w-80">{children}</TooltipContent>
        </Tooltip>
    )
}

export function QuillPathsAdvanced({ insightProps, ...rest }: EditorFilterProps): JSX.Element {
    const { pathsFilter } = useValues(pathsDataLogic(insightProps))
    const { updateInsightFilter } = useActions(pathsDataLogic(insightProps))

    const { featureFlags } = useValues(featureFlagLogic)

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

    const onEnter = (e: React.KeyboardEvent<HTMLInputElement>): void => {
        if (e.key === 'Enter') {
            updateEdgeParameters()
        }
    }
    return (
        <div className="flex flex-col gap-4">
            <PayGateMini feature={AvailableFeature.PATHS_ADVANCED} featureDetail="paths-advanced-filter">
                <div className="flex flex-col gap-4">
                    <Field>
                        <FieldLabel htmlFor="paths-edge-limit" className="flex items-center gap-1">
                            Maximum number of paths
                            <InfoTooltip>
                                Determines the maximum number of path nodes that can be generated. If necessary certain
                                items will be grouped.
                            </InfoTooltip>
                        </FieldLabel>
                        <Input
                            id="paths-edge-limit"
                            type="number"
                            min={0}
                            max={1000}
                            defaultValue={localEdgeParameters.edgeLimit || 50}
                            onChange={(e) =>
                                setLocalEdgeParameters((state) => ({
                                    ...state,
                                    edgeLimit: Number(e.target.value),
                                }))
                            }
                            onBlur={updateEdgeParameters}
                            onKeyDown={onEnter}
                        />
                    </Field>
                    <Field>
                        <FieldLabel className="flex items-center gap-1">
                            Number of people on each path
                            <InfoTooltip>
                                Determines the minimum and maximum number of persons in each path. Helps adjust the
                                density of the visualization.
                            </InfoTooltip>
                        </FieldLabel>
                        <div className="flex items-center gap-2">
                            <span>Between</span>
                            <Input
                                type="number"
                                aria-label="Minimum persons on each path"
                                min={0}
                                max={100000}
                                defaultValue={localEdgeParameters.minEdgeWeight}
                                onChange={(e) => {
                                    setLocalEdgeParameters((state) => ({
                                        ...state,
                                        minEdgeWeight: Number(e.target.value),
                                    }))
                                    updateEdgeParameters()
                                }}
                                onBlur={updateEdgeParameters}
                                onKeyDown={onEnter}
                            />
                            <span>and</span>
                            <Input
                                type="number"
                                aria-label="Maximum persons on each path"
                                min={0}
                                max={100000}
                                defaultValue={localEdgeParameters.maxEdgeWeight}
                                onChange={(e) => {
                                    setLocalEdgeParameters((state) => ({
                                        ...state,
                                        maxEdgeWeight: Number(e.target.value),
                                    }))
                                    updateEdgeParameters()
                                }}
                                onBlur={updateEdgeParameters}
                                onKeyDown={onEnter}
                            />
                            <span>persons.</span>
                        </div>
                    </Field>
                    <div className="flex flex-col gap-2">
                        <Text size="xs" weight="medium" render={<span />} className="flex items-center gap-1">
                            Path cleaning rules
                            <InfoTooltip>
                                Cleaning rules are an advanced feature that uses regex to normalize URLS for paths
                                visualization. Rules can be set for all insights in the project settings, or they can be
                                defined specifically for an insight.
                            </InfoTooltip>
                        </Text>
                        <PathCleaningFilter insightProps={insightProps} {...rest} />
                    </div>
                </div>
            </PayGateMini>

            <Field>
                <QuillLabeledSwitch
                    checked={!!showFullUrls}
                    onChange={(checked) => updateInsightFilter({ showFullUrls: checked })}
                    label="Show full URLs"
                />
                <FieldDescription>
                    Display complete URLs instead of truncated versions. Useful for comparing paths side-by-side.
                </FieldDescription>
            </Field>

            {(featureFlags[FEATURE_FLAGS.PRODUCT_ANALYTICS_PATHS_STRIP_QUERY_STRING] || stripQueryString) && (
                <Field>
                    <QuillLabeledSwitch
                        checked={!!stripQueryString}
                        onChange={(checked) => updateInsightFilter({ stripQueryString: checked })}
                        label="Ignore URL query strings"
                    />
                    <FieldDescription>
                        Treat page views that differ only in the query string as the same step. For example,
                        /products?color=red and /products both count as /products.
                    </FieldDescription>
                </Field>
            )}
        </div>
    )
}
