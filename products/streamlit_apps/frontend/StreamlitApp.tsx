import { useActions, useValues } from 'kea'

import { IconPencil } from '@posthog/icons'
import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { StreamlitAppLoading } from './StreamlitAppLoading'
import { StreamlitAppLogicProps, streamlitAppLogic } from './streamlitAppLogic'

export const scene: SceneExport = {
    component: StreamlitAppViewer,
    logic: streamlitAppLogic,
    paramsToProps: ({ params: { id } }): StreamlitAppLogicProps => ({
        shortId: id as string,
    }),
}

const GENERIC_ERROR_MESSAGE = 'Something went wrong starting your app. Check the logs or contact support.'

// Keeps raw stack traces and DB errors out of the viewer UI.
const ERROR_PREFIX_MESSAGES: Array<[string, string]> = [
    [
        'Max restart count',
        "We've hit the restart limit for this app. Try editing the source and uploading a new version.",
    ],
    ['Auth proxy failed to become ready', "The app's auth proxy didn't start in time. Try restarting."],
    ['Startup timed out', 'Startup timed out. Try restarting.'],
    ['Sandbox terminated', 'The sandbox stopped unexpectedly. Restart to try again.'],
    ['No active version', 'No version uploaded yet. Upload a zip file from the edit page.'],
]

function curateErrorMessage(raw?: string | null): string {
    if (!raw) {
        return GENERIC_ERROR_MESSAGE
    }
    for (const [prefix, friendly] of ERROR_PREFIX_MESSAGES) {
        if (raw.startsWith(prefix)) {
            return friendly
        }
    }
    return GENERIC_ERROR_MESSAGE
}

export function StreamlitAppViewer(props: Record<string, any>): JSX.Element {
    const streamlitAppsFeatureFlagEnabled = useFeatureFlag('STREAMLIT_APPS')
    const shortId = props.id as string
    const { streamlitApp, streamlitAppLoading, appStatus, iframeSrc, sandboxStatus, connectError } = useValues(
        streamlitAppLogic({ shortId })
    )
    const { startApp, restartApp, loadConnectInfo } = useActions(streamlitAppLogic({ shortId }))

    if (!streamlitAppsFeatureFlagEnabled) {
        return <NotFound object="page" />
    }

    if (streamlitAppLoading && !streamlitApp) {
        return (
            <div className="flex items-center justify-center py-20">
                <Spinner className="text-4xl" />
            </div>
        )
    }

    if (!streamlitApp) {
        return (
            <div className="flex flex-col items-center justify-center py-20 text-center">
                <h2 className="text-lg font-semibold mb-2">App not found</h2>
                <p className="text-muted mb-4">This Streamlit app doesn't exist or you don't have access to it.</p>
                <LemonButton type="primary" to={urls.streamlitApps()}>
                    Back to apps
                </LemonButton>
            </div>
        )
    }

    return (
        <div className="flex flex-col h-full">
            <SceneTitleSection
                name={streamlitApp.name}
                resourceType={{ type: 'streamlit_app' }}
                actions={
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconPencil />}
                        to={urls.streamlitAppEdit(streamlitApp.short_id)}
                    >
                        Edit
                    </LemonButton>
                }
            />
            {/* Nudge on version mismatch between activated and running versions. */}
            {appStatus === 'running' &&
                streamlitApp.active_version &&
                sandboxStatus?.version_number != null &&
                streamlitApp.active_version.version_number !== sandboxStatus.version_number && (
                    <LemonBanner
                        type="info"
                        className="mb-2"
                        action={{
                            children: 'Restart now',
                            onClick: () => restartApp(),
                        }}
                    >
                        New version available — restart to apply the changes.
                    </LemonBanner>
                )}
            <div className="flex-1 min-h-0">
                {appStatus === 'starting' && <StreamlitAppLoading />}

                {appStatus === 'stopping' && <StreamlitAppLoading message="Stopping the app..." />}

                {appStatus === 'running' && iframeSrc && (
                    <iframe
                        src={iframeSrc}
                        // allow-same-origin lets Streamlit read its own cookies/sessionStorage.
                        // PostHog is a different origin, so the proxy's scope check is the real boundary.
                        sandbox="allow-scripts allow-forms allow-popups allow-modals allow-same-origin"
                        referrerPolicy="no-referrer"
                        className="w-full h-full border-0 rounded-lg"
                        style={{ minHeight: '600px' }}
                        title={streamlitApp.name}
                    />
                )}

                {appStatus === 'running' && !iframeSrc && connectError && (
                    <div className="flex flex-col items-center justify-center py-20 text-center">
                        <h2 className="text-lg font-semibold mb-2">Connection failed</h2>
                        <p className="text-muted mb-6">{connectError}</p>
                        <LemonButton type="primary" onClick={() => loadConnectInfo()}>
                            Retry
                        </LemonButton>
                    </div>
                )}

                {appStatus === 'running' && !iframeSrc && !connectError && <StreamlitAppLoading />}

                {appStatus === 'error' && (
                    <div className="flex flex-col items-center justify-center py-20 text-center">
                        <h2 className="text-lg font-semibold mb-2">App failed to start</h2>
                        <p className="text-muted mb-4 max-w-lg">{curateErrorMessage(sandboxStatus?.last_error)}</p>
                        <div className="flex gap-2">
                            <LemonButton type="primary" onClick={restartApp}>
                                Try again
                            </LemonButton>
                            <LemonButton type="secondary" to={urls.streamlitAppEdit(streamlitApp.short_id)}>
                                View settings
                            </LemonButton>
                        </div>
                    </div>
                )}

                {appStatus === 'stopped' && !streamlitApp.active_version && (
                    <div className="flex flex-col items-center justify-center py-20 text-center">
                        <h2 className="text-lg font-semibold mb-2">No version uploaded</h2>
                        <p className="text-muted mb-4">Upload a zip file to get started.</p>
                        <LemonButton type="primary" to={urls.streamlitAppEdit(streamlitApp.short_id)}>
                            Upload
                        </LemonButton>
                    </div>
                )}

                {appStatus === 'stopped' && streamlitApp.active_version && (
                    <div className="flex flex-col items-center justify-center py-20 text-center">
                        <h2 className="text-lg font-semibold mb-2">App is stopped</h2>
                        <p className="text-muted mb-4">Start the app to view it.</p>
                        <LemonButton type="primary" onClick={startApp}>
                            Start app
                        </LemonButton>
                    </div>
                )}
            </div>
        </div>
    )
}
