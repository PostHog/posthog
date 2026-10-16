import { useActions, useValues } from 'kea'

import { Button, Card, CardContent, CardDescription, CardHeader, CardTitle, Skeleton, Text } from 'lib/ui/quill'

import { ImpactIssueList } from './ImpactIssueList'
import { ImpactLensBoundary } from './ImpactLensBoundary'
import { IMPACT_LENS_INFO } from './impactLenses'
import { ImpactLensStatus } from './ImpactLensStatus'
import { type ImpactView, impactTabLogic } from './impactTabLogic'

const lensCount = (count: number): string => `${count} ${count === 1 ? 'lens' : 'lenses'}`

function PanelMessage({ children }: { children: React.ReactNode }): JSX.Element {
    return <div className="flex flex-col items-start gap-2 px-3 pb-4">{children}</div>
}

function ViewBody({ view }: { view: ImpactView }): JSX.Element {
    const { viewStatus, activeFindings, lensesByType, uncalculatedCount } = useValues(impactTabLogic)
    const { refreshLens, refreshUncalculatedLenses } = useActions(impactTabLogic)
    const lens = view === 'all' ? undefined : lensesByType[view]

    switch (viewStatus) {
        case 'calculating':
            return (
                <div className="flex flex-col gap-2 px-3 pb-3">
                    <Text size="sm" variant="muted">
                        {view === 'all' ? `Calculating ${lensCount(uncalculatedCount)}.` : 'Calculating this lens.'}
                    </Text>
                    <Skeleton className="h-12 w-full" />
                    <Skeleton className="h-12 w-full" />
                    <Skeleton className="h-12 w-full" />
                </div>
            )
        case 'not_calculated':
            return (
                <PanelMessage>
                    <Text size="sm" variant="muted">
                        {view === 'all'
                            ? `${lensCount(uncalculatedCount)} haven't been calculated yet.`
                            : "This lens hasn't been calculated yet."}
                    </Text>
                    <Button
                        variant="outline"
                        size="sm"
                        onClick={() => (lens ? refreshLens(lens.id) : refreshUncalculatedLenses())}
                        data-attr="error-tracking-impact-calculate"
                    >
                        Calculate now
                    </Button>
                </PanelMessage>
            )
        case 'unavailable':
            return (
                <PanelMessage>
                    <Text size="sm" variant="muted">
                        {view === 'all'
                            ? 'None of the lenses can run on this project yet. Pick a lens to see what it needs.'
                            : `This lens can't run on this project yet. ${IMPACT_LENS_INFO[view].unavailableReason}.`}
                    </Text>
                </PanelMessage>
            )
        case 'empty':
            return (
                <PanelMessage>
                    <Text size="sm" variant="muted">
                        Nothing was flagged.
                    </Text>
                </PanelMessage>
            )
        case 'ready':
            return <ImpactIssueList findings={activeFindings} showLens={view === 'all'} />
    }
}

// The open view: what it shows and how, then every item in one list.
export function ImpactLensPanel({ view }: { view: ImpactView }): JSX.Element {
    const { lenses, lensesByType, lensStates, uncalculatedCount, unavailableCount } = useValues(impactTabLogic)
    const recommendation = view === 'all' ? undefined : lensesByType[view]
    const state = view === 'all' ? undefined : lensStates[view]
    // In the All view a missing lens can hide items, so say so next to whatever the other lenses found.
    const allViewNotes = [
        uncalculatedCount > 0 ? `${lensCount(uncalculatedCount)} still calculating.` : null,
        unavailableCount > 0 ? `${lensCount(unavailableCount)} can't run on this project.` : null,
    ].filter((note): note is string => note !== null)

    return (
        <Card size="sm" flush className="min-w-0">
            <CardHeader className="flex flex-col gap-1">
                <div className="flex flex-wrap items-center justify-between gap-2">
                    {/* quill renders CardTitle as a plain div, so the role restores heading semantics. */}
                    <CardTitle role="heading" aria-level={3}>
                        {view === 'all' ? 'All lenses' : IMPACT_LENS_INFO[view].label}
                    </CardTitle>
                    {recommendation && state && <ImpactLensStatus lens={recommendation} state={state} />}
                </div>
                <CardDescription className="max-w-4xl">
                    {view === 'all'
                        ? 'Every issue a lens flagged, in one list. Issues that are likely noise are left out, see Hidden as noise. Pick a lens to see how it decides what to flag.'
                        : IMPACT_LENS_INFO[view].description}
                </CardDescription>
                {view === 'all' && allViewNotes.length > 0 && (
                    <Text size="xs" variant="muted">
                        {allViewNotes.join(' ')}
                    </Text>
                )}
            </CardHeader>
            <CardContent>
                <ImpactLensBoundary view={view} resetKey={lenses.map((lens) => lens.computed_at).join()}>
                    <ViewBody view={view} />
                </ImpactLensBoundary>
            </CardContent>
        </Card>
    )
}
