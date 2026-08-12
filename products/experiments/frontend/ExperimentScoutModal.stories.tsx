import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import type { Meta, StoryObj } from '@storybook/react'
import { useActions, useMountedLogic } from 'kea'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'
import type { Experiment } from '~/types'

import { experimentScoutLogic, type ExperimentScoutModalStep } from './experimentScoutLogic'
import { ExperimentScoutModal } from './ExperimentScoutModal'

const EXPERIMENT_ID = 123

interface ExperimentScoutModalStoryProps {
    step: Exclude<ExperimentScoutModalStep, null>
}

function ExperimentScoutModalStory({ step }: ExperimentScoutModalStoryProps): JSX.Element {
    const logic = experimentScoutLogic({ experimentId: EXPERIMENT_ID })
    useMountedLogic(logic)
    const { closeExperimentScoutModal, launchExperimentSuccess, openExperimentScoutSetup, openSelfDrivingSetup } =
        useActions(logic)

    useEffect(() => {
        if (step === 'launch-success') {
            launchExperimentSuccess({ id: EXPERIMENT_ID } as Experiment)
        } else if (step === 'self-driving-setup') {
            openSelfDrivingSetup()
        } else {
            openExperimentScoutSetup()
        }

        return () => {
            closeExperimentScoutModal()
        }
    }, [closeExperimentScoutModal, launchExperimentSuccess, openExperimentScoutSetup, openSelfDrivingSetup, step])

    return <ExperimentScoutModal experimentId={EXPERIMENT_ID} />
}

const noGitHubIntegrationMocks = {
    get: {
        '/api/environments/:team_id/integrations/': { results: [] },
        '/api/projects/:team_id/integrations/github/available_installations/': {
            installations: [],
            personal_github_connected: false,
        },
    },
}

const selfDrivingSetupMocks = {
    get: {
        ...noGitHubIntegrationMocks.get,
        '/api/organizations/@current/': {
            ...MOCK_DEFAULT_ORGANIZATION,
            is_ai_data_processing_approved: false,
        },
    },
}

const connectedGitHubMocks = {
    get: {
        '/api/environments/:team_id/integrations/': {
            results: [
                {
                    id: 7,
                    kind: 'github',
                    display_name: 'example-org',
                    config: {},
                    created_at: '2026-08-12T00:00:00Z',
                },
            ],
        },
    },
}

const enrolledScoutMocks = {
    get: {
        '/api/projects/:team_id/signals/scout/metadata/current/': {
            enrolled: true,
            banner_message: null,
            limits: {},
        },
        '/api/projects/:team_id/signals/scout/configs/': [],
        '/api/projects/:team_id/signals/source_configs/': { count: 0, results: [] },
    },
}

const meta: Meta<typeof ExperimentScoutModalStory> = {
    title: 'Scenes-App/Experiments/Launch scout flow',
    component: ExperimentScoutModalStory,
    args: {
        step: 'launch-success',
    },
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        featureFlags: {
            [FEATURE_FLAGS.EXPERIMENT_LAUNCH_SCOUT_FLOW]: 'test',
            [FEATURE_FLAGS.PRODUCT_AUTONOMY]: true,
        },
    },
    decorators: [mswDecorator(enrolledScoutMocks)],
}

export default meta

type Story = StoryObj<typeof ExperimentScoutModalStory>

export const LaunchConfirmation: Story = {
    parameters: {
        docs: {
            description: {
                story: 'The confirmation shown after an experiment launches. The user can dismiss it or continue to scout setup.',
            },
        },
    },
}

export const SelfDrivingEnablement: Story = {
    args: {
        step: 'self-driving-setup',
    },
    parameters: {
        docs: {
            description: {
                story: 'Step two for a project that still needs Self-driving. The recommended Wizard command sits above the manual AI processing and GitHub controls.',
            },
        },
        msw: {
            mocks: selfDrivingSetupMocks,
        },
    },
}

export const ScoutSetupWithoutGitHub: Story = {
    args: {
        step: 'scout-setup',
    },
    parameters: {
        docs: {
            description: {
                story: 'The final scout form fallback when GitHub is not connected. The connection control remains available here for direct links and interrupted setup flows.',
            },
        },
        msw: {
            mocks: noGitHubIntegrationMocks,
        },
    },
}

export const ScoutSetupWithGitHub: Story = {
    args: {
        step: 'scout-setup',
    },
    parameters: {
        docs: {
            description: {
                story: 'Step three with prefilled experiment instructions after Self-driving is ready. No repository selection is required.',
            },
        },
        msw: {
            mocks: connectedGitHubMocks,
        },
    },
}
