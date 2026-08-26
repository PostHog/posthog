import { useValues } from 'kea'

import { Separator, Text } from 'lib/ui/quill'

import { BUILT_IN_ERROR_TRACKING_PROPERTIES } from '../builtInProperties'
import { IssueFilterPreviewHeader } from '../IssueFilterPreview/IssueFilterPreviewHeader'
import { BreakdownDetailsDialog } from './BreakdownDetailsDialog'
import { BreakdownsTileButton } from './BreakdownsTileButton'
import { BreakdownPreset } from './consts'
import { miniBreakdownsLogic } from './miniBreakdownsLogic'

const BUILT_IN_PROPERTY_NAMES = new Set(BUILT_IN_ERROR_TRACKING_PROPERTIES.map(({ property }) => property))

export function MiniBreakdowns(): JSX.Element {
    const { visibleBreakdownProperties } = useValues(miniBreakdownsLogic)
    const builtInProperties = visibleBreakdownProperties.filter(({ property }) => BUILT_IN_PROPERTY_NAMES.has(property))
    const customProperties = visibleBreakdownProperties.filter(({ property }) => !BUILT_IN_PROPERTY_NAMES.has(property))

    return (
        <div className="flex flex-col">
            <IssueFilterPreviewHeader preview="properties" title="Breakdown" />
            <div className="grid content-start grid-cols-[fit-content(12rem)_minmax(0,1fr)] gap-y-px pb-6 pt-1">
                {builtInProperties.length > 0 && (
                    <BreakdownPropertySection
                        id="built-in-breakdown-properties"
                        title="Built-in properties"
                        properties={builtInProperties}
                    />
                )}
                {customProperties.length > 0 && (
                    <BreakdownPropertySection
                        id="custom-breakdown-properties"
                        title="Custom properties"
                        properties={customProperties}
                    />
                )}
            </div>
            <BreakdownDetailsDialog />
        </div>
    )
}

function BreakdownPropertySection({
    id,
    title,
    properties,
}: {
    id: string
    title: string
    properties: BreakdownPreset[]
}): JSX.Element {
    return (
        <section aria-labelledby={id} className="contents">
            <div className="col-span-2 flex h-10 items-center gap-3 px-2.5">
                <Separator className="min-w-0 flex-1" />
                <Text
                    id={id}
                    size="xxs"
                    variant="muted"
                    weight="semibold"
                    render={<h3 />}
                    className="!mb-0 shrink-0 text-center uppercase tracking-wide"
                >
                    {title}
                </Text>
                <Separator className="min-w-0 flex-1" />
            </div>
            {properties.map((item) => (
                <BreakdownsTileButton key={item.property} item={item} />
            ))}
        </section>
    )
}
