import { useActions } from 'kea'

import { IconChevronDown } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { CalcColumnState } from '../useInsightsTableModel'
import { CALC_COLUMN_LABELS } from './AggregationColumn'

interface QuillAggregationMenuProps {
    aggregation: CalcColumnState
    setAggregationType: (state: CalcColumnState) => void
}

export function QuillAggregationMenu({ aggregation, setAggregationType }: QuillAggregationMenuProps): JSX.Element {
    const { reportInsightsTableCalcToggled } = useActions(eventUsageLogic)

    return (
        <DropdownMenu>
            {/* The trigger's own data-slot hides it from the table's header-button styles, so it takes them here. */}
            <DropdownMenuTrigger
                render={
                    <Button
                        size="sm"
                        className="-mx-2 align-middle text-xxs font-medium uppercase tracking-wider text-inherit"
                    />
                }
            >
                {CALC_COLUMN_LABELS[aggregation]}
                <IconChevronDown />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
                <DropdownMenuRadioGroup
                    value={aggregation}
                    onValueChange={(value: CalcColumnState) => {
                        setAggregationType(value)
                        reportInsightsTableCalcToggled(value)
                    }}
                >
                    {Object.entries(CALC_COLUMN_LABELS).map(([key, label]) => (
                        <DropdownMenuRadioItem key={key} value={key}>
                            {label}
                        </DropdownMenuRadioItem>
                    ))}
                </DropdownMenuRadioGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
