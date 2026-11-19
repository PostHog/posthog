// PROTOTYPE (throwaway): messages ranked by opens, clicks or sends, each a link to its broadcast or workflow.
import { useMemo, useState } from 'react'

import { Button, ToggleGroup, ToggleGroupItem } from '@posthog/quill'
import { BarList } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'

import { ChartCard } from './ChartCard'
import { EmptyInsight } from './EmptyInsight'
import { TOP_MESSAGES_R3 } from './insightsData'
import { KIND_LABEL, formatCount } from './prototypeData'
import { prototypeToast } from './prototypeToast'

const CONFIG = { valueDisplay: 'value' as const, rowHeight: 40 }

type Rank = 'opened' | 'clicked' | 'sent'
const RANKS: { value: Rank; label: string }[] = [
    { value: 'opened', label: 'Opened' },
    { value: 'clicked', label: 'Clicked' },
    { value: 'sent', label: 'Sent' },
]

export function TopMessagesCard({ noSends }: { noSends: boolean }): JSX.Element {
    const theme = useChartTheme()
    const [rank, setRank] = useState<Rank>('clicked')
    const series = useMemo(
        () =>
            TOP_MESSAGES_R3.map((m) => ({
                key: m.key,
                label: m.label,
                data: [
                    rank === 'sent' ? m.sent : Math.round((rank === 'opened' ? m.openRate : m.clickRate) * 1000) / 10,
                ],
                meta: m,
            })).sort((a, b) => b.data[0] - a.data[0]),
        [rank]
    )
    return (
        <ChartCard
            title="Top messages"
            description="At least 500 sent"
            action={
                noSends ? null : (
                    <ToggleGroup
                        variant="outline"
                        size="sm"
                        aria-label="Rank by"
                        value={[rank]}
                        onValueChange={(next: string[]) => next[0] && setRank(next[0] as Rank)}
                    >
                        {RANKS.map((r) => (
                            <ToggleGroupItem key={r.value} value={r.value}>
                                {r.label}
                            </ToggleGroupItem>
                        ))}
                    </ToggleGroup>
                )
            }
        >
            {noSends ? (
                <EmptyInsight
                    title="No messages sent yet"
                    detail="Your broadcasts, workflows and transactional emails rank here by how often people click."
                />
            ) : (
                <div className="flex h-56 flex-col">
                    <BarList
                        series={series}
                        theme={theme}
                        config={CONFIG}
                        valueFormatter={(v) => (rank === 'sent' ? formatCount(v) : `${v.toFixed(1)}%`)}
                        renderLabel={(s) => (
                            <span className="flex min-w-0 flex-col items-start leading-tight">
                                <Button
                                    variant="link"
                                    size="inline"
                                    className="max-w-full truncate"
                                    onClick={() => prototypeToast(s.label)}
                                >
                                    {s.label}
                                </Button>
                                <span className="text-xxs text-muted-foreground">
                                    {KIND_LABEL[s.meta!.kind]} · {formatCount(s.meta!.sent)} sent
                                </span>
                            </span>
                        )}
                    />
                </div>
            )}
        </ChartCard>
    )
}
