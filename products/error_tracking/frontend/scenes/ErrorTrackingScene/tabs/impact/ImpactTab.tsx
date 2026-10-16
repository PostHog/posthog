import { useActions, useValues } from 'kea'

import { Button, Skeleton, Text, TooltipProvider } from 'lib/ui/quill'

import { ImpactLensBar } from './ImpactLensBar'
import { ImpactLensBoundary } from './ImpactLensBoundary'
import { ImpactLensPanel } from './ImpactLensPanel'
import { impactTabLogic } from './impactTabLogic'

export function ImpactTab(): JSX.Element {
    const { tabStatus, activeView, lenses, recommendationsLoading } = useValues(impactTabLogic)
    const { loadRecommendations } = useActions(impactTabLogic)

    if (tabStatus === 'loading') {
        return (
            <div data-quill className="flex flex-col gap-3">
                <Skeleton className="h-8 w-full" />
                <Skeleton className="h-96 w-full" />
            </div>
        )
    }
    if (tabStatus === 'error') {
        return (
            <div data-quill className="flex flex-col items-start gap-2">
                <Text size="sm" variant="muted">
                    Couldn't load the impact lenses. Try again, and if it keeps happening contact support.
                </Text>
                <Button
                    variant="outline"
                    size="sm"
                    loading={recommendationsLoading}
                    onClick={loadRecommendations}
                    data-attr="error-tracking-impact-retry"
                >
                    Try again
                </Button>
            </div>
        )
    }
    if (tabStatus === 'off') {
        return (
            <div data-quill>
                <Text size="sm" variant="muted">
                    Impact lenses aren't turned on for this project yet.
                </Text>
            </div>
        )
    }

    return (
        <TooltipProvider>
            <div data-quill className="@container/impact flex flex-col gap-4">
                <ImpactLensBoundary view={activeView} resetKey={lenses.map((lens) => lens.computed_at).join()}>
                    <ImpactLensBar />
                    <ImpactLensPanel view={activeView} />
                </ImpactLensBoundary>
            </div>
        </TooltipProvider>
    )
}
