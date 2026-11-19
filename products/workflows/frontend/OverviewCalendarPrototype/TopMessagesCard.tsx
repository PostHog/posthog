import { useMemo } from 'react'

import { Button } from '@posthog/quill'
// PROTOTYPE (throwaway): the messages that get the most clicks, each a link to its broadcast or workflow.
import { BarList } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'

import { ChartCard } from './ChartCard'
import { EmptyInsight } from './EmptyInsight'
import { TOP_MESSAGES_R3 } from './insightsData'
import { KIND_LABEL, formatCount } from './prototypeData'
import { prototypeToast } from './prototypeToast'

const CONFIG = { valueDisplay: 'value' as const, rowHeight: 40 }

export function TopMessagesCard({ noSends }: { noSends: boolean }): JSX.Element {
    const theme = useChartTheme()
    const series = useMemo(
        () =>
            TOP_MESSAGES_R3.map((m) => ({
                key: m.key,
                label: m.label,
                data: [Math.round(m.clickRate * 1000) / 10],
                meta: m,
            })),
        []
    )
    return (
        <ChartCard title="Top messages by click rate" description="At least 500 sent">
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
                        valueFormatter={(v) => `${v.toFixed(1)}%`}
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
