import { MakeLogicType, actions, afterMount, connect, kea, key, listeners, path, props, reducers } from 'kea'
import posthog from 'posthog-js'

import { cloudEnvironmentsLogic } from 'scenes/settings/environment/cloudEnvironmentsLogic'
import { cloudImagesLogic } from 'scenes/settings/environment/cloudImagesLogic'

import type { SandboxCustomImageDTOApi, SandboxEnvironmentDTOApi } from 'products/tasks/frontend/generated/api.schemas'

import { cloudTargetKey, standaloneReadyImages } from '../../utils/cloudTargets'
import { taskTrackerSceneLogic } from './taskTrackerSceneLogic'

export interface ComposerSandboxEnvironmentsLogicProps {
    panelId?: string
}

export interface composerSandboxEnvironmentsLogicValues {
    awaitingCreatedEnvironment: boolean
    environments: SandboxEnvironmentDTOApi[] | null
    images: SandboxCustomImageDTOApi[] | null
    unavailable: boolean
}

export interface composerSandboxEnvironmentsLogicActions {
    closeDraft: () => { value: true }
    environmentCreated: (environment: SandboxEnvironmentDTOApi) => { environment: SandboxEnvironmentDTOApi }
    loadEnvironmentsSuccess: (
        environments: SandboxEnvironmentDTOApi[] | null,
        payload?: any
    ) => { environments: SandboxEnvironmentDTOApi[] | null; payload?: any }
    loadImagesSuccess: (
        images: SandboxCustomImageDTOApi[] | null,
        payload?: any
    ) => { images: SandboxCustomImageDTOApi[] | null; payload?: any }
    imagesUnavailable: () => { value: true }
    startNewEnvironment: () => { value: true }
    pickCloudTarget: (cloudTarget: string | null) => { cloudTarget: string | null }
    setCloudTargets: (
        environments: SandboxEnvironmentDTOApi[] | null,
        images: SandboxCustomImageDTOApi[] | null
    ) => { environments: SandboxEnvironmentDTOApi[] | null; images: SandboxCustomImageDTOApi[] | null }
    createEnvironment: () => { value: true }
    syncCloudTargets: () => { value: true }
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
        values: [cloudEnvironmentsLogic, ['environments'], cloudImagesLogic, ['images', 'unavailable']],
        actions: [
            cloudEnvironmentsLogic,
            ['loadEnvironmentsSuccess', 'environmentCreated', 'closeDraft', 'startNewEnvironment'],
            cloudImagesLogic,
            ['loadImagesSuccess', 'imagesUnavailable'],
            taskTrackerSceneLogic({ panelId: props.panelId }),
            ['pickCloudTarget', 'setCloudTargets'],
        ],
    })),
    actions({
        createEnvironment: true,
        syncCloudTargets: true,
    }),
    reducers({
        awaitingCreatedEnvironment: [
            false,
            {
                createEnvironment: () => true,
                closeDraft: () => false,
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        syncCloudTargets: () => {
            const images = values.unavailable ? [] : standaloneReadyImages(values.images, values.environments)
            actions.setCloudTargets(values.environments, images)
        },
        loadEnvironmentsSuccess: () => actions.syncCloudTargets(),
        loadImagesSuccess: () => actions.syncCloudTargets(),
        imagesUnavailable: () => actions.syncCloudTargets(),
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
            actions.setCloudTargets(environments, standaloneReadyImages(values.images, environments))
            actions.pickCloudTarget(cloudTargetKey('environment', environment.id))
        },
    })),
    afterMount(({ actions }) => {
        actions.syncCloudTargets()
    }),
])
