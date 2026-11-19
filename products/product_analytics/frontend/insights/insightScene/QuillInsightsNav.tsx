import { Badge, Tabs, TabsList, TabsTrigger, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { INSIGHT_TYPE_URLS } from 'scenes/insights/utils'
import { INSIGHT_TYPES_METADATA } from 'scenes/saved-insights/insightTypesMetadata'

import { InsightType } from '~/types'

import type { Tab } from 'products/product_analytics/frontend/insights/InsightNav/insightNavLogic'

export interface QuillInsightsNavProps {
    tabs: Tab[]
    activeView: InsightType
    onChange: (type: InsightType) => void
}

export function QuillInsightsNav({ tabs, activeView, onChange }: QuillInsightsNavProps): JSX.Element {
    return (
        <Tabs
            value={activeView}
            onValueChange={(value) => onChange(value as InsightType)}
            className="border-b border-border"
            data-quill
        >
            <TabsList variant="line" className="max-w-full justify-start overflow-x-auto">
                {tabs.map(({ label, type, dataAttr, beta }) => {
                    const metadata = INSIGHT_TYPES_METADATA[type]
                    const docLink = metadata.tooltipDocLink
                    const Icon = metadata.icon
                    return (
                        <TabsTrigger key={type} value={type}>
                            <LinkPrimitive
                                to={INSIGHT_TYPE_URLS[type]}
                                preventClick
                                className="text-inherit hover:text-inherit"
                                data-attr={dataAttr}
                            >
                                <Tooltip>
                                    <TooltipTrigger render={<span className="inline-flex items-center gap-1.5" />}>
                                        <Icon className="size-3.5 shrink-0" />
                                        {label}
                                        {beta && <Badge variant="warning">Beta</Badge>}
                                    </TooltipTrigger>
                                    <TooltipContent side="top">
                                        <div className="flex flex-col gap-1">
                                            <span>{metadata.tooltipDescription || metadata.description}</span>
                                            {docLink && (
                                                <LinkPrimitive
                                                    to={docLink}
                                                    target="_blank"
                                                    className="text-xs text-primary-on-foreground underline"
                                                    data-ph-capture-attribute-autocapture-event-name="clicked tooltip doc link"
                                                    data-ph-capture-attribute-doclink={docLink}
                                                >
                                                    Read the docs
                                                </LinkPrimitive>
                                            )}
                                        </div>
                                    </TooltipContent>
                                </Tooltip>
                            </LinkPrimitive>
                        </TabsTrigger>
                    )
                })}
            </TabsList>
        </Tabs>
    )
}
