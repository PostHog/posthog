import { mswDecorator } from '~/mocks/browser'
import { toPaginatedResponse } from '~/mocks/handlers'

import type { IntegrationConfigApi } from 'products/integrations/frontend/generated/api.schemas'

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
export const globalTemplates = (
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

export const WELCOME_SEQUENCE_ID = welcomeEmailSequence.id
export const TRIAL_UPGRADE_NUDGE_ID = trialStartedUpgradeNudge.id
export const RE_ENGAGEMENT_ID = reEngagement.id

export const OWN_SENDER: Partial<IntegrationConfigApi> = {
    id: 7,
    kind: 'email',
    display_name: 'Example <sender@example.com>',
    config: { verified: true, email: 'sender@example.com', name: 'Example' },
    created_at: '2026-10-01T00:00:00Z',
}

export function projectThatSends(seenEvents: string[]): Parameters<typeof mswDecorator>[0] {
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
