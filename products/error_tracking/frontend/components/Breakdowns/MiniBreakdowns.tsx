import { useValues } from 'kea'

import { Text } from 'lib/ui/quill'

import { IssueFilterPreviewHeader } from '../IssueFilterPreview/IssueFilterPreviewHeader'
import { BreakdownDetailsDialog } from './BreakdownDetailsDialog'
import { BreakdownsTileButton } from './BreakdownsTileButton'
import { BREAKDOWN_PRESETS, BreakdownPreset } from './consts'
import { miniBreakdownsLogic } from './miniBreakdownsLogic'

const BUILT_IN_PROPERTY_NAMES = new Set(BREAKDOWN_PRESETS.map(({ property }) => property))

export function MiniBreakdowns(): JSX.Element {
    const { breakdownProperties } = useValues(miniBreakdownsLogic)
    const builtInProperties = breakdownProperties.filter(({ property }) => BUILT_IN_PROPERTY_NAMES.has(property))
    const customProperties = breakdownProperties.filter(({ property }) => !BUILT_IN_PROPERTY_NAMES.has(property))

    return (
        <div className="flex flex-col">
            <IssueFilterPreviewHeader preview="properties" title="Breakdown" />
            <div className="grid content-start grid-cols-[fit-content(12rem)_minmax(0,1fr)] gap-y-px pb-6 pt-1">
                <BreakdownPropertySection
                    id="built-in-breakdown-properties"
                    title="Built-in properties"
                    properties={builtInProperties}
                />
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
            <Text
                id={id}
                size="xxs"
                variant="muted"
                weight="semibold"
                render={<h3 />}
                className="!mb-0 col-span-2 flex h-10 items-center justify-center px-2.5 text-center uppercase tracking-wide"
            >
                {title}
            </Text>
            {properties.map((item) => (
                <BreakdownsTileButton key={item.property} item={item} />
            ))}
        </section>
    )
}
