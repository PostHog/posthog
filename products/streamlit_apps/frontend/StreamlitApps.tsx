import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconEllipsis, IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import type { AppSummaryContractApi } from './generated/api.schemas'
import { streamlitAppsLogic } from './streamlitAppsLogic'
import { StreamlitAppStatus, toStreamlitAppStatus } from './types'

export const scene: SceneExport = {
    component: StreamlitApps,
    logic: streamlitAppsLogic,
}

const STATUS_CONFIG: Record<StreamlitAppStatus, { label: string; type: LemonTagType }> = {
    running: { label: 'Running', type: 'success' },
    starting: { label: 'Starting', type: 'warning' },
    stopping: { label: 'Stopping', type: 'default' },
    stopped: { label: 'Stopped', type: 'default' },
    error: { label: 'Error', type: 'danger' },
}

function AppCard({ app }: { app: AppSummaryContractApi }): JSX.Element {
    const config = STATUS_CONFIG[toStreamlitAppStatus(app.status)]
    const { deleteStreamlitApp } = useActions(streamlitAppsLogic)

    const openApp = (): void => {
        router.actions.push(urls.streamlitApp(app.short_id))
    }

    return (
        <div
            className="border rounded-lg p-4 cursor-pointer hover:shadow-md transition-shadow bg-bg-light focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary"
            onClick={openApp}
            onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    openApp()
                }
            }}
            role="link"
            tabIndex={0}
            aria-label={`Open ${app.name}`}
        >
            <div className="flex items-start justify-between mb-2">
                <h3 className="font-semibold text-base m-0 truncate">{app.name}</h3>
                <div className="flex items-center gap-1">
                    <LemonTag type={config.type}>{config.label}</LemonTag>
                    <LemonMenu
                        items={[
                            {
                                label: 'Delete',
                                icon: <IconTrash />,
                                status: 'danger',
                                onClick: () => {
                                    LemonDialog.open({
                                        title: 'Delete app?',
                                        description:
                                            'This will permanently delete this app and all its versions. This cannot be undone.',
                                        primaryButton: {
                                            children: 'Delete',
                                            status: 'danger',
                                            onClick: () => deleteStreamlitApp({ shortId: app.short_id }),
                                        },
                                        secondaryButton: {
                                            children: 'Cancel',
                                        },
                                    })
                                },
                            },
                        ]}
                        placement="bottom-end"
                    >
                        <LemonButton
                            size="xsmall"
                            noPadding
                            icon={<IconEllipsis />}
                            onClick={(e) => e.stopPropagation()}
                        />
                    </LemonMenu>
                </div>
            </div>
            {app.description && <p className="text-muted text-sm mb-2 line-clamp-2 m-0">{app.description}</p>}
            <div className="flex items-center justify-end text-xs text-muted mt-3">
                <span>{app.created_by?.first_name ?? 'Unknown'}</span>
            </div>
        </div>
    )
}

export function StreamlitApps(): JSX.Element {
    const streamlitAppsFeatureFlagEnabled = useFeatureFlag('STREAMLIT_APPS')
    const { streamlitApps, streamlitAppsLoading } = useValues(streamlitAppsLogic)

    if (!streamlitAppsFeatureFlagEnabled) {
        return <NotFound object="page" />
    }

    return (
        <div>
            <div className="flex items-center justify-between mb-4">
                <h1 className="text-2xl font-bold m-0">Apps</h1>
                <LemonButton type="primary" icon={<IconPlus />} to={urls.streamlitAppNew()}>
                    New app
                </LemonButton>
            </div>

            {streamlitAppsLoading && streamlitApps.length === 0 ? (
                <div className="flex items-center justify-center py-20">
                    <Spinner className="text-4xl" />
                </div>
            ) : streamlitApps.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-20 text-center">
                    <h2 className="text-lg font-semibold mb-2">No apps yet</h2>
                    <p className="text-muted mb-4">Create your first Streamlit app to get started.</p>
                    <LemonButton type="primary" icon={<IconPlus />} to={urls.streamlitAppNew()}>
                        New app
                    </LemonButton>
                </div>
            ) : (
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                    {streamlitApps.map((app) => (
                        <AppCard key={app.id} app={app} />
                    ))}
                </div>
            )}
        </div>
    )
}
