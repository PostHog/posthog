import { useActions, useValues } from 'kea'

import { IconPencil } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

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

export function StreamlitAppViewer(props: Record<string, any>): JSX.Element {
    const shortId = props.id as string
    const { streamlitApp, streamlitAppLoading, appStatus, iframeSrc, sandboxStatus } = useValues(
        streamlitAppLogic({ shortId })
    )
    const { startApp, restartApp } = useActions(streamlitAppLogic({ shortId }))

    if (streamlitAppLoading && !streamlitApp) {
        return (
            <div className="flex items-center justify-center py-20">
                <Spinner className="text-4xl" />
            </div>
        )
    }

    if (!streamlitApp) {
        return <div className="text-center py-20 text-muted">App not found</div>
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
            <div className="flex-1 min-h-0">
                {appStatus === 'starting' && <StreamlitAppLoading />}

                {appStatus === 'running' && iframeSrc && (
                    <iframe
                        src={iframeSrc}
                        sandbox="allow-scripts allow-forms allow-popups allow-modals allow-same-origin"
                        className="w-full h-full border-0 rounded-lg"
                        style={{ minHeight: '600px' }}
                        title={streamlitApp.name}
                    />
                )}

                {appStatus === 'running' && !iframeSrc && <StreamlitAppLoading />}

                {appStatus === 'error' && (
                    <div className="flex flex-col items-center justify-center py-20 text-center">
                        <h2 className="text-lg font-semibold mb-2">App failed to start</h2>
                        {sandboxStatus?.last_error && (
                            <p className="text-muted mb-4 font-mono text-sm max-w-lg">{sandboxStatus.last_error}</p>
                        )}
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

                {sandboxStatus &&
                    sandboxStatus.current_viewers >= sandboxStatus.max_viewers &&
                    appStatus === 'running' &&
                    !iframeSrc && (
                        <div className="flex flex-col items-center justify-center py-20 text-center">
                            <h2 className="text-lg font-semibold mb-2">App is busy</h2>
                            <p className="text-muted mb-4">
                                This app has reached its viewer limit ({sandboxStatus.max_viewers}). Please try again in
                                a few minutes.
                            </p>
                            <LemonButton type="primary" onClick={() => window.location.reload()}>
                                Refresh
                            </LemonButton>
                        </div>
                    )}
            </div>
        </div>
    )
}
