import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { streamlitAppEditLogicType } from './streamlitAppEditLogicType'
import { streamlitAppsLogic } from './streamlitAppsLogic'
import { StreamlitAppType, StreamlitAppVersion } from './types'

export interface StreamlitAppEditLogicProps {
    shortId: string
}

export const streamlitAppEditLogic = kea<streamlitAppEditLogicType>([
    path(['products', 'streamlit_apps', 'frontend', 'streamlitAppEditLogic']),
    props({} as StreamlitAppEditLogicProps),
    key((props) => props.shortId),

    actions({
        setName: (name: string) => ({ name }),
        setDescription: (description: string) => ({ description }),
        setCpuCores: (cpuCores: number) => ({ cpuCores }),
        setMemoryGb: (memoryGb: number) => ({ memoryGb }),
        setZipFile: (file: File | null) => ({ file }),
        setActiveVersionNumber: (versionNumber: number) => ({ versionNumber }),
        // Narrow update; dispatching loadStreamlitAppSuccess would clobber unsaved form edits.
        setActiveVersionInState: (activeVersion: StreamlitAppVersion) => ({ activeVersion }),
    }),

    loaders(({ props, values }) => ({
        streamlitApp: [
            null as StreamlitAppType | null,
            {
                loadStreamlitApp: async () => {
                    if (props.shortId === 'new') {
                        return null
                    }
                    return await api.streamlitApps.get(props.shortId)
                },
            },
        ],
        versions: [
            [] as StreamlitAppVersion[],
            {
                loadVersions: async () => {
                    if (props.shortId === 'new') {
                        return []
                    }
                    const response = await api.streamlitApps.versions(props.shortId)
                    return response.results
                },
            },
        ],
        savedApp: [
            null as StreamlitAppType | null,
            {
                saveApp: async () => {
                    const isNew = props.shortId === 'new'

                    let app: StreamlitAppType
                    if (isNew) {
                        app = await api.streamlitApps.create({
                            name: values.name,
                            description: values.description,
                            cpu_cores: values.cpuCores,
                            memory_gb: values.memoryGb,
                        })
                    } else {
                        app = await api.streamlitApps.update(props.shortId, {
                            name: values.name,
                            description: values.description,
                            cpu_cores: values.cpuCores,
                            memory_gb: values.memoryGb,
                        })
                    }

                    if (values.zipFile) {
                        try {
                            await api.streamlitApps.uploadVersion(app.short_id, values.zipFile)
                            app = await api.streamlitApps.get(app.short_id)
                        } catch {
                            lemonToast.error('App created but zip upload failed. You can retry from the edit page.')
                            router.actions.push(urls.streamlitAppEdit(app.short_id))
                            return app
                        }
                    }

                    lemonToast.success(isNew ? 'App created' : 'App saved')
                    if (isNew) {
                        router.actions.push(urls.streamlitApp(app.short_id))
                    }
                    return app
                },
                deleteApp: async () => {
                    await api.streamlitApps.delete(props.shortId)
                    lemonToast.success('App deleted')
                    streamlitAppsLogic.findMounted()?.actions.loadStreamlitApps()
                    router.actions.push(urls.streamlitApps())
                    return null
                },
            },
        ],
    })),

    reducers({
        streamlitApp: {
            setActiveVersionInState: (state: StreamlitAppType | null, { activeVersion }) =>
                state ? { ...state, active_version: activeVersion } : state,
        },
        name: [
            '',
            {
                setName: (_, { name }) => name,
                loadStreamlitAppSuccess: (_, { streamlitApp }) => streamlitApp?.name ?? '',
            },
        ],
        description: [
            '',
            {
                setDescription: (_, { description }) => description,
                loadStreamlitAppSuccess: (_, { streamlitApp }) => streamlitApp?.description ?? '',
            },
        ],
        cpuCores: [
            0.5,
            {
                setCpuCores: (_, { cpuCores }) => cpuCores,
                loadStreamlitAppSuccess: (_, { streamlitApp }) => streamlitApp?.cpu_cores ?? 0.5,
            },
        ],
        memoryGb: [
            1,
            {
                setMemoryGb: (_, { memoryGb }) => memoryGb,
                loadStreamlitAppSuccess: (_, { streamlitApp }) => streamlitApp?.memory_gb ?? 1,
            },
        ],
        zipFile: [
            null as File | null,
            {
                setZipFile: (_, { file }) => file,
            },
        ],
    }),

    selectors({
        breadcrumbs: [
            (s) => [s.streamlitApp],
            (streamlitApp): Breadcrumb[] => [
                {
                    key: 'StreamlitApps',
                    name: 'Apps',
                    path: urls.streamlitApps(),
                },
                {
                    key: ['StreamlitAppEdit', streamlitApp?.short_id || 'new'],
                    name: streamlitApp ? streamlitApp.name : 'New app',
                },
            ],
        ],
    }),

    listeners(({ props, values, actions }) => ({
        saveAppSuccess: ({ savedApp }) => {
            if (savedApp) {
                streamlitAppsLogic.findMounted()?.actions.updateStreamlitApp(savedApp)
            }
        },
        setActiveVersionNumber: async ({ versionNumber }) => {
            if (props.shortId === 'new') {
                return
            }
            try {
                const response = await api.streamlitApps.activateVersion(props.shortId, versionNumber)
                lemonToast.success(`Switched to v${versionNumber}. Restart the app to apply.`)
                const nextActiveVersion = response?.active_version ?? values.streamlitApp?.active_version ?? null
                if (values.streamlitApp && nextActiveVersion) {
                    // Narrow update; see setActiveVersionInState for rationale.
                    actions.setActiveVersionInState(nextActiveVersion)
                    streamlitAppsLogic.findMounted()?.actions.updateStreamlitApp({
                        ...values.streamlitApp,
                        active_version: nextActiveVersion,
                    })
                }
            } catch (error: any) {
                lemonToast.error(
                    `Failed to activate v${versionNumber}: ${error?.detail || error?.message || 'unknown error'}`
                )
            }
        },
    })),

    afterMount(({ props, actions }) => {
        if (props.shortId !== 'new') {
            actions.loadStreamlitApp()
            actions.loadVersions()
        }
    }),
])
