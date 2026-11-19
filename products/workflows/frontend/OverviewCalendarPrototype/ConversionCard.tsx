import { useMemo } from 'react'

import { IconChevronDown } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuTrigger,
} from '@posthog/quill'
// PROTOTYPE (throwaway): from message to conversion, with the goal picker that defines "converted".
import { FunnelChart, funnelFromCounts } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'

import { ChartCard } from './ChartCard'
import { EmptyInsight } from './EmptyInsight'
import { CONVERSION_GOALS } from './insightsData'
import { formatCount } from './prototypeData'

function GoalPicker({
    goal,
    onGoal,
    label,
}: {
    goal: string | null
    onGoal: (goal: string) => void
    label?: string
}): JSX.Element {
    const current = CONVERSION_GOALS.find((g) => g.key === goal)
    return (
        <DropdownMenu>
            <DropdownMenuTrigger render={<Button variant={current ? 'outline' : 'primary'} size="sm" />}>
                {label ?? (current ? `Goal: ${current.label}` : 'Pick a conversion goal')}
                <IconChevronDown />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
                <DropdownMenuRadioGroup value={goal ?? ''} onValueChange={(value) => onGoal(String(value))}>
                    {CONVERSION_GOALS.map((g) => (
                        <DropdownMenuRadioItem key={g.key} value={g.key}>
                            {g.label}
                        </DropdownMenuRadioItem>
                    ))}
                </DropdownMenuRadioGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

export function ConversionCard({
    steps,
    goal,
    onGoal,
    noSends,
}: {
    steps: { label: string; count: number }[]
    goal: string | null
    onGoal: (goal: string) => void
    noSends: boolean
}): JSX.Element {
    const theme = useChartTheme()
    const funnel = useMemo(() => funnelFromCounts(steps, { label: 'Messages' }), [steps])
    return (
        <ChartCard
            title="From message to conversion"
            description="Converted: did the goal within 7 days of a click"
            action={goal ? <GoalPicker goal={goal} onGoal={onGoal} /> : null}
        >
            {!goal ? (
                <EmptyInsight
                    title="Pick what counts as a conversion"
                    detail="Choose the event that matters, such as an upgrade or a sign-up, to see which messages lead to it."
                >
                    <GoalPicker goal={goal} onGoal={onGoal} />
                </EmptyInsight>
            ) : noSends ? (
                <EmptyInsight
                    title="No messages sent yet"
                    detail="Once people click a link in a message, this shows how many go on to reach your goal."
                />
            ) : (
                <div className="flex h-64 flex-col">
                    <FunnelChart
                        steps={funnel.steps}
                        series={funnel.series}
                        theme={theme}
                        stepFooter={(i) => (
                            <div className="text-xs leading-tight">
                                <div className="truncate font-semibold">{funnel.steps[i]}</div>
                                <div className="text-muted-foreground">{formatCount(steps[i]?.count ?? 0)}</div>
                            </div>
                        )}
                    />
                </div>
            )}
        </ChartCard>
    )
}
