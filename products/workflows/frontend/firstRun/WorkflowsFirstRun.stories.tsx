import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'
import { useMountedLogic } from 'kea'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { EMPTY_PAGINATED_RESPONSE, toPaginatedResponse } from '~/mocks/handlers'

import announceANewFeature from '../../backend/templates/announce_a_new_feature_template.json'
import celebrateMilestone from '../../backend/templates/celebrate-milestone.json'
import featureAdoptionTips from '../../backend/templates/feature-adoption-tips.json'
import heavyUsageDetected from '../../backend/templates/heavy-usage-detected.json'
import highIntentNotification from '../../backend/templates/high-intent-notification.json'
import onboardingStarted from '../../backend/templates/onboarding_started_but_not_completed_template.json'
import reEngagement from '../../backend/templates/re-engagement-workflow.json'
import trialEndingReminder from '../../backend/templates/trial-ending-reminder.json'
import trialStartedUpgradeNudge from '../../backend/templates/trial_started_upgrade_nudge_template.json'
import unlockingAdvancedFeatures from '../../backend/templates/unlocking_advanced_features.json'
import unusedFeaturesEducation from '../../backend/templates/unused-features-education.json'
import welcomeEmailSequence from '../../backend/templates/welcome_email_sequence_template.json'
import type { HogFlowTemplateApi } from '../generated/api.schemas'

// The global templates in the order the API lists them, plus one without an email step that the gallery leaves out.
// The serializer defaults `tags` to an empty list, which some template files leave out.
const globalTemplates = (
    [
        announceANewFeature,
        onboardingStarted,
        trialStartedUpgradeNudge,
        welcomeEmailSequence,
        celebrateMilestone,
        featureAdoptionTips,
        heavyUsageDetected,
        highIntentNotification,
        reEngagement,
        trialEndingReminder,
        unlockingAdvancedFeatures,
        unusedFeaturesEducation,
    ] as unknown as HogFlowTemplateApi[]
).map((template) => ({ ...template, tags: template.tags ?? [] }))

function projectThatSends(seenEvents: string[]): Parameters<typeof mswDecorator>[0] {
    return {
        get: {
            '/api/projects/:team_id/event_definitions/': ({ request }) => {
                const names = new URL(request.url).searchParams.get('names')?.split(',') ?? []
                const seen = names.filter((name) => seenEvents.includes(name))
                return [
                    200,
                    toPaginatedResponse(seen.map((name) => ({ id: name, name, last_seen_at: '2026-10-01T00:00:00Z' }))),
                ]
            },
        },
    }
}

const meta: Meta = {
    component: App,
    title: 'Products/Workflows/First run gallery',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-10-05',
        pageUrl: urls.workflows(),
        featureFlags: [FEATURE_FLAGS.WORKFLOWS_FIRST_RUN],
        testOptions: { viewport: { width: 1440, height: 2400 } },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/hog_flows/': EMPTY_PAGINATED_RESPONSE,
                '/api/projects/:team_id/hog_flows/email_sending_suspension/': {
                    email_sending_suspended: false,
                    email_sending_suspended_at: null,
                    email_sending_suspension_reason: '',
                },
                '/api/projects/:team_id/hog_flow_templates/': toPaginatedResponse(globalTemplates),
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const ProjectWithSignups: Story = {
    decorators: [mswDecorator(projectThatSends(['signed_up', '$pageview', '$feature_view']))],
}

export const ProjectWithOnlyPageviews: Story = {
    decorators: [mswDecorator(projectThatSends(['$pageview']))],
}

export const ProjectWithNoEvents: Story = {
    decorators: [mswDecorator(projectThatSends([]))],
    render: function ProjectWithNoEvents(): JSX.Element {
        useMountedLogic(teamLogic)
        useEffect(() => {
            teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, ingested_event: false })
        }, [])
        return <App />
    },
}

// A docked side panel leaves the scene about 520px wide on a laptop. This viewport gives the scene the same width.
export const ProjectWithSignupsInANarrowScene: Story = {
    decorators: [mswDecorator(projectThatSends(['signed_up', '$pageview', '$feature_view']))],
    parameters: { testOptions: { viewport: { width: 552, height: 2400 } } },
}
