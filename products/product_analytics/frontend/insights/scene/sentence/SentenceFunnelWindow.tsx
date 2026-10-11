import { useActions, useValues } from 'kea'

import { DropdownMenu, DropdownMenuContent, DropdownMenuRadioGroup, DropdownMenuTrigger } from '@posthog/quill'

import { FunnelConversionWindowTimeUnit } from '~/types'
import type { InsightLogicProps } from '~/types'

import { MenuChoiceItem } from '../MenuChoiceItem'
import { EditableWord } from './EditableWord'
import { insightSentenceLogic } from './insightSentenceLogic'

interface FunnelWindow {
    interval: number
    unit: FunnelConversionWindowTimeUnit
}

const WINDOWS: FunnelWindow[] = [
    { interval: 30, unit: FunnelConversionWindowTimeUnit.Minute },
    { interval: 1, unit: FunnelConversionWindowTimeUnit.Hour },
    { interval: 1, unit: FunnelConversionWindowTimeUnit.Day },
    { interval: 7, unit: FunnelConversionWindowTimeUnit.Day },
    { interval: 14, unit: FunnelConversionWindowTimeUnit.Day },
    { interval: 30, unit: FunnelConversionWindowTimeUnit.Day },
    { interval: 90, unit: FunnelConversionWindowTimeUnit.Day },
]

function windowKey({ interval, unit }: FunnelWindow): string {
    return `${interval}:${unit}`
}

function windowLabel({ interval, unit }: FunnelWindow): string {
    return `${interval} ${unit}${interval === 1 ? '' : 's'}`
}

export function SentenceFunnelWindow({
    insightProps,
    label,
}: {
    insightProps: InsightLogicProps
    label: string
}): JSX.Element {
    const { funnelsQuery } = useValues(insightSentenceLogic(insightProps))
    const { changeFunnelWindow } = useActions(insightSentenceLogic(insightProps))
    const current: FunnelWindow = {
        interval: funnelsQuery?.funnelsFilter?.funnelWindowInterval ?? 14,
        unit: funnelsQuery?.funnelsFilter?.funnelWindowIntervalUnit ?? FunnelConversionWindowTimeUnit.Day,
    }
    // A window set elsewhere may not be in the list, and it still has to show as the current choice.
    const windows = WINDOWS.some((option) => windowKey(option) === windowKey(current)) ? WINDOWS : [current, ...WINDOWS]

    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={<EditableWord color="orange" data-attr="quill-insight-sentence-funnel-window" />}
            >
                {label}
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="min-w-56">
                <DropdownMenuRadioGroup
                    value={windowKey(current)}
                    onValueChange={(value: string) => {
                        const picked = windows.find((option) => windowKey(option) === value)
                        if (picked) {
                            changeFunnelWindow(picked.interval, picked.unit)
                        }
                    }}
                >
                    {windows.map((option) => (
                        <MenuChoiceItem key={windowKey(option)} value={windowKey(option)}>
                            {windowLabel(option)}
                        </MenuChoiceItem>
                    ))}
                </DropdownMenuRadioGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
