import { useActions, useValues } from 'kea'

import { IconExternal } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { ListHog } from 'lib/components/hedgehogs'
import { useInterval } from 'lib/hooks/useInterval'
import { teamLogic } from 'scenes/teamLogic'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

import { logsIngestionLogic } from './logsIngestionLogic'

const POLLING_INTERVAL_MS = 5000

export const LogsSetupPrompt = ({
    children,
    className,
}: {
    children: React.ReactNode
    className?: string
}): JSX.Element => {
    const { hasLogs, teamHasLogsLoading, teamHasLogsCheckFailed } = useValues(logsIngestionLogic)
    const { currentTeam } = useValues(teamLogic)

    if ((teamHasLogsLoading && hasLogs === undefined) || !currentTeam) {
        return (
            <div className="flex justify-center">
                <Spinner />
            </div>
        )
    }

    if (teamHasLogsCheckFailed || hasLogs === undefined) {
        return <>{children}</>
    }

    if (!hasLogs) {
        return <NoLogsPrompt className={className} />
    }

    return <>{children}</>
}

const NoLogsPrompt = ({ className }: { className?: string }): JSX.Element | null => {
    const { addProductIntent } = useActions(teamLogic)
    const { hasLogs } = useValues(logsIngestionLogic)
    const { loadTeamHasLogs } = useActions(logsIngestionLogic)

    useInterval(() => {
        if (!hasLogs) {
            loadTeamHasLogs()
        }
    }, POLLING_INTERVAL_MS)

    return (
        <ProductIntroduction
            productName="Logs"
            thingName="log"
            titleOverride="You haven't sent any logs yet"
            description="PostHog logs works with any OpenTelemetry-compatible client. You don't need any PostHog-specific packages – just use standard OpenTelemetry libraries to send logs via OTLP."
            isEmpty={true}
            productKey={ProductKey.LOGS}
            className={className}
            customHog={ListHog}
            actionElementOverride={
                <div className="flex flex-col items-start gap-4">
                    <LemonButton
                        type="primary"
                        targetBlank
                        sideIcon={<IconExternal className="w-5 h-5" />}
                        to="https://posthog.com/docs/logs/"
                        onClick={() => {
                            addProductIntent({
                                product_type: ProductKey.LOGS,
                                intent_context: ProductIntentContext.LOGS_DOCS_VIEWED,
                            })
                        }}
                    >
                        Configure your logging client
                    </LemonButton>
                    <div className="flex items-center gap-2 px-3 py-1.5 border border-accent rounded">
                        <div className="relative flex items-center justify-center">
                            <div className="absolute w-3 h-3 border-2 border-accent rounded-full animate-ping" />
                            <div className="w-2 h-2 bg-accent rounded-full" />
                        </div>
                        <span className="text-sm">Watching for logs</span>
                    </div>
                </div>
            }
        />
    )
}
