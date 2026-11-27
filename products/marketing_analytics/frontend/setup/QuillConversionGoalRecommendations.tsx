import type { ReactNode } from 'react'

import {
    Button,
    Card,
    CardContent,
    CardDescription,
    CardFooter,
    CardTitle,
    Collapsible,
    CollapsibleContent,
    CollapsibleTrigger,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    Spinner,
    Text,
} from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'

import type { ConversionRecommendationApi } from '../generated/api.schemas'
import type { conversionRecommendationsLogicValues } from './conversionRecommendationsLogic'
import { QuillConversionRecommendationCard } from './QuillConversionRecommendationCard'

export function QuillConversionGoalRecommendations({
    state,
    stateLoading,
    isAnalyzing,
    error,
    pendingRecommendations,
    allRecommendationsConfigured,
    allRecommendationsHandled,
    dismissedRecommendationEntries,
    scanCooldownRemaining,
    scanDisabledReason,
    editDisabledReason,
    recommendationDisabledReason,
    headerAction,
    onConfigureGoals,
    onUseSuggestion,
    onDismiss,
    onRestore,
    onRetryLoading,
    onScan,
}: Pick<
    conversionRecommendationsLogicValues,
    | 'state'
    | 'stateLoading'
    | 'isAnalyzing'
    | 'error'
    | 'pendingRecommendations'
    | 'allRecommendationsConfigured'
    | 'allRecommendationsHandled'
    | 'dismissedRecommendationEntries'
    | 'scanCooldownRemaining'
    | 'scanDisabledReason'
> & {
    editDisabledReason: string | null
    recommendationDisabledReason: string | null | undefined
    headerAction?: ReactNode
    onConfigureGoals: () => void
    onUseSuggestion: (recommendation: ConversionRecommendationApi) => void
    onDismiss: (recommendation: ConversionRecommendationApi) => void
    onRestore: (sourceRef: string) => void
    onRetryLoading: () => void
    onScan: () => void
}): JSX.Element {
    return (
        <Card className="mt-4" data-attr="marketing-conversion-recommendations">
            {/* No CardHeader: its divider would double up with the list's own top border. */}
            <CardContent className="flex flex-col gap-3">
                <div className="flex items-start justify-between gap-3">
                    <div className="flex min-w-0 flex-col gap-1">
                        <CardTitle>
                            {allRecommendationsConfigured ? 'Conversion goals' : 'Suggested conversion goals'}
                        </CardTitle>
                        <CardDescription>
                            {allRecommendationsConfigured
                                ? 'All suggestions from your last successful scan are configured.'
                                : allRecommendationsHandled && dismissedRecommendationEntries.length > 0
                                  ? 'No pending suggestions. You can review and restore dismissed suggestions below.'
                                  : 'Review suggested events and actions before adding a goal.'}
                        </CardDescription>
                    </div>
                    {headerAction}
                </div>
                {state?.generation_disabled_reason && (
                    <Item tone="info" size="sm">
                        <ItemContent>
                            <ItemDescription>{state.generation_disabled_reason}</ItemDescription>
                        </ItemContent>
                    </Item>
                )}
                {!state && stateLoading && (
                    <Item tone="info" size="sm">
                        <ItemContent>
                            <ItemDescription>Loading conversion recommendations…</ItemDescription>
                        </ItemContent>
                    </Item>
                )}
                {isAnalyzing && (
                    <Item tone="info" size="sm">
                        <ItemContent>
                            <ItemDescription>
                                Scanning events and actions from the last {state?.latest_run?.lookback_days} days.{' '}
                                {state?.result_run
                                    ? 'Previous suggestions remain available.'
                                    : 'You can leave this page while it runs.'}
                            </ItemDescription>
                        </ItemContent>
                    </Item>
                )}
                {error && (
                    <Item tone="destructive" size="sm" className="flex-wrap">
                        <ItemContent>
                            <ItemDescription>{error}</ItemDescription>
                        </ItemContent>
                        <ItemActions>
                            <Button
                                variant="outline"
                                onClick={onRetryLoading}
                                disabledReason={stateLoading ? 'Wait for the current request.' : undefined}
                            >
                                Retry loading
                            </Button>
                        </ItemActions>
                    </Item>
                )}
                {state?.latest_run?.status === 'failed' && (
                    <Item tone="warning" size="sm">
                        <ItemContent>
                            <ItemDescription>
                                {allRecommendationsConfigured
                                    ? 'The latest scan failed. Your configured goals are unchanged. Scan again to retry.'
                                    : state.result_run
                                      ? 'The latest scan failed. Suggestions from your last successful scan are still available. Scan again to retry.'
                                      : 'Could not scan events and actions. Scan again to retry.'}
                            </ItemDescription>
                        </ItemContent>
                    </Item>
                )}
                {state?.result_run && (state.results.recommendations?.length ?? 0) === 0 && (
                    <Item tone="info" size="sm">
                        <ItemContent>
                            <ItemDescription>
                                No additional goals were found. Review your configured goals or scan again after more
                                data arrives.
                            </ItemDescription>
                        </ItemContent>
                    </Item>
                )}
                {pendingRecommendations.length > 0 && (
                    <div className="flex flex-col divide-y divide-border border-t border-border">
                        {pendingRecommendations.map((recommendation) => (
                            <QuillConversionRecommendationCard
                                key={recommendation.source_ref}
                                recommendation={recommendation}
                                onUseSuggestion={() => onUseSuggestion(recommendation)}
                                onDismiss={() => onDismiss(recommendation)}
                                disabledReason={recommendationDisabledReason}
                            />
                        ))}
                    </div>
                )}
                {dismissedRecommendationEntries.length > 0 && (
                    <Collapsible>
                        <CollapsibleTrigger>{`Dismissed suggestions (${dismissedRecommendationEntries.length})`}</CollapsibleTrigger>
                        <CollapsibleContent className="flex flex-col gap-2">
                            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                Hidden for you in this browser. Restore a suggestion to show it again if it is in the
                                latest scan, or allow it in future scans.
                            </Text>
                            <div className="flex flex-col divide-y divide-border">
                                {dismissedRecommendationEntries.map((recommendation) => (
                                    <div
                                        key={recommendation.source_ref}
                                        className="flex flex-wrap items-center justify-between gap-2 py-2"
                                    >
                                        <div className="flex min-w-0 flex-1 basis-48 flex-col">
                                            <Text
                                                size="xs"
                                                weight="semibold"
                                                render={<span className="m-0 break-words" />}
                                            >
                                                {recommendation.name}
                                            </Text>
                                            <Text size="xs" variant="muted" render={<span className="m-0 break-all" />}>
                                                {recommendation.source_ref}
                                            </Text>
                                        </div>
                                        <Button
                                            variant="outline"
                                            onClick={() => onRestore(recommendation.source_ref)}
                                            data-attr="marketing-conversion-restore-suggestion"
                                        >
                                            Restore
                                        </Button>
                                    </div>
                                ))}
                            </div>
                        </CollapsibleContent>
                    </Collapsible>
                )}
                {(state?.result_run ||
                    state?.latest_run?.status === 'failed' ||
                    !!state?.results.limitations?.length) && (
                    <Collapsible>
                        <CollapsibleTrigger>Scan details</CollapsibleTrigger>
                        <CollapsibleContent className="flex flex-col gap-2 text-xs text-muted-foreground">
                            {state?.result_run && (
                                <p className="m-0">
                                    <span>Analysis period: </span>
                                    <TZLabel time={state.result_run.date_from} timestampStyle="absolute" />
                                    <span> to </span>
                                    <TZLabel time={state.result_run.date_to} timestampStyle="absolute" />
                                    <span>. Applied suggestions are hidden.</span>
                                </p>
                            )}
                            {state?.latest_run?.status === 'failed' && state.latest_run.error && (
                                <p className="m-0">{state.latest_run.error}</p>
                            )}
                            {!!state?.results.limitations?.length && (
                                <ul className="m-0 list-disc pl-5">
                                    {state.results.limitations.map((limitation) => (
                                        <li key={limitation}>{limitation}</li>
                                    ))}
                                </ul>
                            )}
                        </CollapsibleContent>
                    </Collapsible>
                )}
            </CardContent>
            <CardFooter className="flex-wrap justify-between gap-2">
                <Button variant="outline" onClick={onConfigureGoals} data-attr="marketing-conversion-configure-goals">
                    Configure goals
                </Button>
                <div className="flex flex-wrap items-center gap-2">
                    {!isAnalyzing && scanCooldownRemaining > 0 && state?.can_generate && (
                        <Text size="xs" variant="muted" render={<span className="m-0" />}>
                            {scanDisabledReason}
                        </Text>
                    )}
                    <Button
                        variant="outline"
                        // `loading` hides the label, and a scan runs long enough that the label has to stay.
                        loading={stateLoading && !isAnalyzing}
                        disabledReason={
                            editDisabledReason ?? scanDisabledReason ?? (isAnalyzing ? 'Scanning…' : undefined)
                        }
                        onClick={onScan}
                        data-attr="marketing-conversion-update-recommendations"
                    >
                        <span>{isAnalyzing ? 'Scanning…' : state?.latest_run ? 'Scan again' : 'Scan events'}</span>
                        {isAnalyzing && <Spinner />}
                    </Button>
                </div>
            </CardFooter>
        </Card>
    )
}
