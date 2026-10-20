import { MakeLogicType, actions, afterMount, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import { projectLogic } from 'scenes/projectLogic'
import { cloudEnvironmentsLogic } from 'scenes/settings/environment/cloudEnvironmentsLogic'

import { sandboxCustomImagesList } from 'products/tasks/frontend/generated/api'
import {
    type SandboxCustomImageDTOApi,
    type SandboxEnvironmentDTOApi,
    SandboxCustomImagesListOriginProduct,
} from 'products/tasks/frontend/generated/api.schemas'

import { cloudTargetKey, standaloneReadyImages } from '../../utils/cloudTargets'
import { taskTrackerSceneLogic } from './taskTrackerSceneLogic'

export interface ComposerSandboxEnvironmentsLogicProps {
    panelId?: string
}

export interface composerSandboxEnvironmentsLogicValues {
    currentProjectId: number | null
    environments: SandboxEnvironmentDTOApi[] | null
    environmentsFailed: boolean
    awaitingCreatedEnvironment: boolean
    images: SandboxCustomImageDTOApi[] | null
    imagesLoading: boolean
    imagesUnavailable: boolean
    imagesFailed: boolean
}

export interface composerSandboxEnvironmentsLogicActions {
    closeDraft: () => { value: true }
    environmentCreated: (environment: SandboxEnvironmentDTOApi) => { environment: SandboxEnvironmentDTOApi }
    loadEnvironments: () => any
    loadEnvironmentsSuccess: (
        environments: SandboxEnvironmentDTOApi[] | null,
        payload?: any
    ) => { environments: SandboxEnvironmentDTOApi[] | null; payload?: any }
    startNewEnvironment: () => { value: true }
    pickCloudTarget: (cloudTarget: string | null) => { cloudTarget: string | null }
    setCloudTargets: (
        environments: SandboxEnvironmentDTOApi[] | null,
        images: SandboxCustomImageDTOApi[] | null
    ) => { environments: SandboxEnvironmentDTOApi[] | null; images: SandboxCustomImageDTOApi[] | null }
    createEnvironment: () => { value: true }
    syncCloudTargets: () => { value: true }
    retryCloudTargets: () => { value: true }
    markImagesUnavailable: () => { value: true }
    loadImages: () => any
    loadImagesSuccess: (
        images: SandboxCustomImageDTOApi[] | null,
        payload?: any
    ) => { images: SandboxCustomImageDTOApi[] | null; payload?: any }
    loadImagesFailure: (error: string, errorObject?: any) => { error: string; errorObject?: any }
}

export type composerSandboxEnvironmentsLogicType = MakeLogicType<
    composerSandboxEnvironmentsLogicValues,
    composerSandboxEnvironmentsLogicActions,
    ComposerSandboxEnvironmentsLogicProps
>

export const composerSandboxEnvironmentsLogic = kea<composerSandboxEnvironmentsLogicType>([
    path(['products', 'posthog_ai', 'frontend', 'scenes', 'TaskTracker', 'composerSandboxEnvironmentsLogic']),
    props({} as ComposerSandboxEnvironmentsLogicProps),
    key((props) => props.panelId ?? 'scene'),
    connect((props: ComposerSandboxEnvironmentsLogicProps) => ({
        values: [projectLogic, ['currentProjectId'], cloudEnvironmentsLogic, ['environments', 'environmentsFailed']],
        actions: [
            cloudEnvironmentsLogic,
            ['loadEnvironments', 'loadEnvironmentsSuccess', 'environmentCreated', 'closeDraft', 'startNewEnvironment'],
            taskTrackerSceneLogic({ panelId: props.panelId }),
            ['pickCloudTarget', 'setCloudTargets'],
        ],
    })),
    actions({
        createEnvironment: true,
        syncCloudTargets: true,
        retryCloudTargets: true,
        markImagesUnavailable: true,
    }),
    loaders(({ values, actions }) => ({
        images: [
            null as SandboxCustomImageDTOApi[] | null,
            {
                loadImages: async (): Promise<SandboxCustomImageDTOApi[] | null> => {
                    if (values.currentProjectId == null) {
                        return null
                    }
                    try {
                        const page = await sandboxCustomImagesList(String(values.currentProjectId), {
                            origin_product: SandboxCustomImagesListOriginProduct.PosthogAi,
                        })
                        return page.results
                    } catch (error: any) {
                        if (error?.status === 403) {
                            actions.markImagesUnavailable()
                            return []
                        }
                        throw error
                    }
                },
            },
        ],
    })),
    reducers({
        awaitingCreatedEnvironment: [
            false,
            {
                createEnvironment: () => true,
                closeDraft: () => false,
            },
        ],
        imagesUnavailable: [false, { markImagesUnavailable: () => true }],
        imagesFailed: [
            false,
            {
                loadImages: () => false,
                loadImagesSuccess: () => false,
                loadImagesFailure: () => true,
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        syncCloudTargets: () => {
            const images = values.images === null ? null : standaloneReadyImages(values.images, values.environments)
            actions.setCloudTargets(values.environments, images)
        },
        loadEnvironmentsSuccess: () => actions.syncCloudTargets(),
        loadImagesSuccess: () => actions.syncCloudTargets(),
        retryCloudTargets: () => {
            if (values.environmentsFailed) {
                actions.loadEnvironments()
            }
            if (values.imagesFailed) {
                actions.loadImages()
            }
        },
        createEnvironment: () => {
            posthog.capture('task composer environment create started')
            actions.startNewEnvironment()
        },
        environmentCreated: ({ environment }) => {
            if (!values.awaitingCreatedEnvironment) {
                return
            }
            posthog.capture('task composer environment created')
            const environments = [
                ...(values.environments ?? []).filter((existing) => existing.id !== environment.id),
                environment,
            ]
            actions.setCloudTargets(
                environments,
                values.images === null ? null : standaloneReadyImages(values.images, environments)
            )
            actions.pickCloudTarget(cloudTargetKey('environment', environment.id))
        },
    })),
    afterMount(({ actions }) => {
        actions.syncCloudTargets()
        actions.loadImages()
    }),
])
