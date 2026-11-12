import { useValues } from 'kea'

import { Badge } from '@posthog/quill'

import { isPropertyMath, mathTagLabel } from 'lib/components/InsightLabel/mathTagLabel'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import type { ResultSeries } from 'scenes/insights/utils/resultSeries'

import { groupsModel } from '~/models/groupsModel'

import { mathsLogic } from 'products/product_analytics/frontend/insights/trends/mathsLogic'

export function QuillMathBadge({ math }: { math: ResultSeries['math'] }): JSX.Element {
    const { mathDefinitions } = useValues(mathsLogic)
    const { aggregationLabel } = useValues(groupsModel)
    const label = mathTagLabel({
        math: math?.math,
        mathHogQL: math?.math_hogql,
        mathGroupTypeIndex: math?.math_group_type_index,
        mathDefinitions,
        aggregationLabel,
    })

    return (
        <span className="flex shrink-0 items-center gap-1">
            <Badge className="max-w-60" title={label}>
                <span className="truncate">{label}</span>
            </Badge>
            {isPropertyMath(math?.math) && math?.math_property && (
                <>
                    <span>of</span>
                    <PropertyKeyInfo disableIcon disablePopover value={math.math_property} />
                </>
            )}
        </span>
    )
}
