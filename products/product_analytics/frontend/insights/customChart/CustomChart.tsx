import { useActions, useValues } from 'kea'

import { LemonBanner, Spinner } from '@posthog/lemon-ui'

import { themeLogic } from 'lib/logic/themeLogic'
import { urls } from 'scenes/urls'

import { BuiltCanvas } from 'products/canvas/frontend/host/BuiltCanvas'

import { CustomChartData } from './customChartData'
import { customChartLogic, RETRY_MESSAGE } from './customChartLogic'

const NO_HIGHLIGHTS: never[] = []
const denyDataRequest = (): Promise<never> => Promise.reject(new Error('A custom chart has no data access'))
const noUserActivation = (): boolean => false
const ignoreExternalOpen = (): void => {}

export interface CustomChartProps {
    canvasId: string
    data: CustomChartData | null
    /** The built-in chart. It shows while the custom chart builds, and when it cannot load. */
    builtInChart: JSX.Element
    /** On a dashboard tile or in another embed, which shows no build status. */
    embedded: boolean
}

export function CustomChart({ canvasId, data, builtInChart, embedded }: CustomChartProps): JSX.Element {
    const logic = customChartLogic({ canvasId })
    const { status, liveBuild, agentWorking, runError, refining } = useValues(logic)
    const { refine, reportRendered, reportRuntimeError } = useActions(logic)
    const { isDarkModeOn } = useValues(themeLogic)

    if (status === 'loading') {
        return (
            <div className="flex flex-1 items-center justify-center min-h-40">
                <Spinner className="text-2xl" />
            </div>
        )
    }

    if (status === 'ready' && liveBuild?.artifact_url && data) {
        return (
            <div className="relative flex flex-1 flex-col min-h-80" data-attr="custom-chart">
                {agentWorking && !embedded && (
                    <div className="absolute top-2 right-2 z-10 flex items-center gap-1 rounded border bg-surface-primary px-2 py-1 text-xs text-secondary">
                        <Spinner />
                        <span>Updating the chart</span>
                    </div>
                )}
                <BuiltCanvas
                    // A new build loads in a fresh frame, so it never runs with the old build's state.
                    key={liveBuild.id}
                    artifactUrl={liveBuild.artifact_url}
                    // A custom chart gets its data pushed in, so it may make no data requests.
                    capabilities={null}
                    theme={isDarkModeOn ? 'dark' : 'light'}
                    insightData={data}
                    onDataRequest={denyDataRequest}
                    onRendered={reportRendered}
                    onError={reportRuntimeError}
                    hasUserActivation={noUserActivation}
                    onOpenExternal={ignoreExternalOpen}
                    commentHighlights={NO_HIGHLIGHTS}
                    clearTextSelectionKey={0}
                />
            </div>
        )
    }

    if (embedded || status === 'unavailable' || status === 'ready') {
        return builtInChart
    }

    return (
        <div className="flex flex-1 flex-col gap-2">
            {status === 'building' ? (
                <LemonBanner type="info" action={{ children: 'Watch the agent', to: urls.canvasDetail(canvasId) }}>
                    The agent is building your custom chart. It takes a few minutes. The built-in chart shows until
                    then.
                </LemonBanner>
            ) : (
                <LemonBanner
                    type="error"
                    action={{
                        children: 'Try again',
                        onClick: () => refine(RETRY_MESSAGE),
                        loading: refining,
                    }}
                >
                    {`The custom chart did not build${runError ? `: ${runError}` : '.'} Try again, or open its canvas to see what happened.`}
                </LemonBanner>
            )}
            {builtInChart}
        </div>
    )
}
