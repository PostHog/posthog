// PROTOTYPE (throwaway): changes the self-driving scout drafts for your messages, each for you to review.
import { IconSparkles } from '@posthog/icons'
import { Badge, Button } from '@posthog/quill'

import { ChartCard } from './ChartCard'
import { EmptyInsight } from './EmptyInsight'
import { SUGGESTIONS } from './insightsData'
import { prototypeToast } from './prototypeToast'

export function SuggestionsCard({ noSends }: { noSends: boolean }): JSX.Element {
    return (
        <ChartCard
            title="Suggested improvements"
            description="The scout watches how your messages do and drafts changes for you to approve."
            action={
                <Badge variant="info">
                    <IconSparkles /> Self-driving
                </Badge>
            }
        >
            {noSends ? (
                <EmptyInsight
                    title="Suggestions start after a few sends"
                    detail="Once a message has gone out a few times, the scout compares sends and suggests what to change."
                />
            ) : (
                <div className="grid gap-3 @min-[56rem]:grid-cols-3">
                    {SUGGESTIONS.map((s) => (
                        <div key={s.key} className="flex flex-col gap-2 rounded-md border p-3">
                            <Button
                                variant="link-muted"
                                size="inline"
                                className="self-start text-xs"
                                onClick={() => prototypeToast(s.message)}
                            >
                                {s.message}
                            </Button>
                            <span className="text-sm font-medium">{s.title}</span>
                            <span className="flex-1 text-xs text-muted-foreground">{s.detail}</span>
                            <div className="flex gap-2">
                                <Button
                                    variant="outline"
                                    size="sm"
                                    onClick={() => prototypeToast('the drafted change')}
                                >
                                    {s.action}
                                </Button>
                                <Button variant="link-muted" size="sm">
                                    Dismiss
                                </Button>
                            </div>
                        </div>
                    ))}
                </div>
            )}
        </ChartCard>
    )
}
