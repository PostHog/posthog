import { useActions, useValues } from 'kea'

import { Separator, Text, ToggleGroup, ToggleGroupItem } from 'lib/ui/quill'

import { type ImpactLensType, isNoiseLensType } from '../recommendations/types'
import { IMPACT_LENS_INFO } from './impactLenses'
import { impactTabLogic } from './impactTabLogic'

export function ImpactLensBar(): JSX.Element {
    const { lensTypes, activeView, lensCounts, lensStates, lensesByType, totalCount } = useValues(impactTabLogic)
    const { selectView } = useActions(impactTabLogic)
    // A count is a verdict, so a lens without results shows none, and neither does one that can't run.
    const hasCount = (type: (typeof lensTypes)[number]): boolean =>
        lensesByType[type]?.computed_at != null && lensStates[type] !== 'unavailable'
    const anyCounted = lensTypes.some((type) => !isNoiseLensType(type) && hasCount(type))
    const noiseLensTypes = lensTypes.filter(isNoiseLensType)
    const chip = (type: ImpactLensType): JSX.Element => (
        <ToggleGroupItem key={type} value={type} data-attr={`error-tracking-impact-lens-${type}`}>
            {IMPACT_LENS_INFO[type].label}
            {hasCount(type) && <span className="text-muted-foreground tabular-nums">{lensCounts[type] ?? 0}</span>}
        </ToggleGroupItem>
    )

    return (
        <ToggleGroup
            variant="outline"
            size="sm"
            spacing={1}
            className="flex-wrap"
            value={[activeView]}
            onValueChange={(value: string[]) => {
                // A click on the open view empties the value, and the tab always shows a view, so it is ignored.
                const view = value[0] === 'all' ? 'all' : lensTypes.find((type) => type === value[0])
                if (view) {
                    selectView(view)
                }
            }}
        >
            <ToggleGroupItem value="all" data-attr="error-tracking-impact-lens-all">
                All
                {anyCounted && <span className="text-muted-foreground tabular-nums">{totalCount}</span>}
            </ToggleGroupItem>
            {lensTypes.filter((type) => !isNoiseLensType(type)).map(chip)}
            {/* The noise lenses explain issues that All leaves out, so they sit apart, after the lenses that count. */}
            {noiseLensTypes.length > 0 && (
                <div className="flex items-center gap-2 px-1">
                    <Separator orientation="vertical" className="h-4" />
                    <Text render={<span />} size="xs" variant="muted">
                        Noise
                    </Text>
                </div>
            )}
            {noiseLensTypes.map(chip)}
        </ToggleGroup>
    )
}
