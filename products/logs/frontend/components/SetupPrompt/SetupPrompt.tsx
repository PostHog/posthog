import { useActions, useValues } from 'kea'

import { IconGear } from '@posthog/icons'
import { LemonButton, Link, Spinner } from '@posthog/lemon-ui'

import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { ListHog } from 'lib/components/hedgehogs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { useInterval } from 'lib/hooks/useInterval'
import goImage from 'scenes/onboarding/sdks/logos/go.svg'
import javaImage from 'scenes/onboarding/sdks/logos/java.svg'
import nextjsImage from 'scenes/onboarding/sdks/logos/nextjs.svg'
import nodejsImage from 'scenes/onboarding/sdks/logos/nodejs.svg'
import pythonImage from 'scenes/onboarding/sdks/logos/python.svg'
import { teamLogic } from 'scenes/teamLogic'

import { sidePanelSettingsLogic } from '~/layout/navigation-3000/sidepanel/panels/sidePanelSettingsLogic'
import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

import { logsIngestionLogic } from './logsIngestionLogic'

const FRAMEWORK_LINKS: { name: string; image?: string; docsLink: string }[] = [
    { name: 'Node.js', image: nodejsImage, docsLink: 'https://posthog.com/docs/logs/installation/nodejs' },
    { name: 'Next.js', image: nextjsImage, docsLink: 'https://posthog.com/docs/logs/installation/nextjs' },
    { name: 'Python', image: pythonImage, docsLink: 'https://posthog.com/docs/logs/installation/python' },
    { name: 'Java', image: javaImage, docsLink: 'https://posthog.com/docs/logs/installation/java' },
    { name: 'Go', image: goImage, docsLink: 'https://posthog.com/docs/logs/installation/go' },
    { name: 'Datadog', docsLink: 'https://posthog.com/docs/logs/installation/datadog' },
    { name: 'Other', docsLink: 'https://posthog.com/docs/logs/installation' },
]

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
    const { openSettingsPanel } = useActions(sidePanelSettingsLogic)
    const hasLogsSettings = useFeatureFlag('LOGS_SETTINGS')

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
                    <p className="text-sm text-secondary m-0">
                        Learn more about{' '}
                        <Link
                            to="https://opentelemetry.io/docs/what-is-opentelemetry/"
                            target="_blank"
                            onClick={() =>
                                addProductIntent({
                                    product_type: ProductKey.LOGS,
                                    intent_context: ProductIntentContext.LOGS_DOCS_VIEWED,
                                })
                            }
                        >
                            OpenTelemetry
                        </Link>
                        , or pick a framework to get started:
                    </p>
                    <div className="flex flex-wrap gap-2">
                        {FRAMEWORK_LINKS.map(({ name, image, docsLink }) => (
                            <LemonButton
                                key={name}
                                type="secondary"
                                size="small"
                                targetBlank
                                to={docsLink}
                                onClick={() => {
                                    addProductIntent({
                                        product_type: ProductKey.LOGS,
                                        intent_context: ProductIntentContext.LOGS_DOCS_VIEWED,
                                    })
                                }}
                                icon={image ? <img src={image} alt={name} className="w-5 h-5" /> : undefined}
                            >
                                {name}
                            </LemonButton>
                        ))}
                    </div>
                    {hasLogsSettings && (
                        <p className="text-sm text-secondary m-0">
                            Already using <code>posthog-js</code>?{' '}
                            <LemonButton
                                type="tertiary"
                                size="xsmall"
                                icon={<IconGear />}
                                onClick={() => {
                                    addProductIntent({
                                        product_type: ProductKey.LOGS,
                                        intent_context: ProductIntentContext.LOGS_SETTINGS_OPENED,
                                    })
                                    openSettingsPanel({
                                        sectionId: 'environment-logs',
                                        settingId: 'logs',
                                    })
                                }}
                            >
                                Enable console log capture
                            </LemonButton>
                        </p>
                    )}
                    <div className="flex items-center gap-4">
                        <div className="flex items-center gap-2 px-3 py-1.5 border border-accent rounded">
                            <div className="relative flex items-center justify-center">
                                <div className="absolute w-3 h-3 border-2 border-accent rounded-full animate-ping" />
                                <div className="w-2 h-2 bg-accent rounded-full" />
                            </div>
                            <span className="text-sm">Watching for logs</span>
                        </div>
                        <span className="text-sm text-secondary">
                            Missing an integration?{' '}
                            <button id="logs-feedback-button" className="text-link font-semibold cursor-pointer">
                                Let us know
                            </button>
                        </span>
                    </div>
                </div>
            }
        />
    )
}
