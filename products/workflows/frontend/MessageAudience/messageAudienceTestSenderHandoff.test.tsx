import '@testing-library/jest-dom'

import { fireEvent, screen, waitFor } from '@testing-library/react'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { workflowLogic } from '../Workflows/workflowLogic'
import { MessageAudience } from './messageAudience'
import { openMessageAudience } from './messageAudienceWarnings'
import { draftMessage } from './messageDrafts'

const properties: MessageAudience['properties'] = [
    { key: 'id', type: PropertyFilterType.Cohort, value: 7, operator: PropertyOperator.In },
]
const email = draftMessage({ kind: 'feature_available', featureName: 'Dark mode' })

function asProp(raw: unknown): string | undefined {
    return raw && typeof raw !== 'string' ? JSON.stringify(raw) : (raw as string | undefined)
}

describe('continuing a broadcast in a workflow with the test sender', () => {
    beforeEach(() => {
        initKeaTests()
        useMocks({
            get: {
                '/api/projects/:team_id/hog_flows/email_sending_suspension/': { email_sending_suspended: false },
                '/api/projects/:team_id/integrations/': { count: 0, results: [], next: null },
                '/api/projects/:team_id/workflow_email_sandbox/status/': {
                    integration_id: 12,
                    from_address: 'test@example.com',
                    display_name: 'Example via PostHog',
                    organization_blocked: false,
                    adoption_enabled: true,
                },
                '/api/projects/:team_id/cohorts/:id/': {
                    name: 'Signups',
                    is_static: true,
                    is_calculating: false,
                },
            },
        })
    })

    afterEach(() => {
        document.body.innerHTML = ''
    })

    it.each<{ case: string; audience: MessageAudience; subject: string | null }>([
        {
            case: 'an email audience',
            audience: { source: 'early_access_feature', properties, broadcastEmail: email },
            subject: email.subject,
        },
        { case: 'a cohort', audience: { source: 'cohort', properties }, subject: null },
    ])('opens the editor on the same people for $case', async ({ audience, subject }) => {
        router.actions.push('/cohorts/7')
        await openMessageAudience(audience, 'broadcast')

        fireEvent.click(await screen.findByText('Continue in a workflow'))
        await waitFor(() => expect(router.values.location.pathname).toContain('/workflows/new'))

        const { searchParams } = router.values
        const logic = workflowLogic({
            id: 'new',
            triggerPrefill: asProp(searchParams.trigger),
            emailPrefill: asProp(searchParams.email),
            entrySource: searchParams.source,
        })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadWorkflowSuccess'])

        const trigger = logic.values.workflow.actions.find((action) => action.type === 'trigger')
        expect(trigger?.config).toEqual({ type: 'batch', filters: { properties } })
        const emailSteps = logic.values.workflow.actions.filter((action) => action.type.includes('email'))
        expect(
            emailSteps.map((action) => ({
                type: action.type,
                subject: (action.config as Record<string, any>).inputs?.email?.value?.subject,
            }))
        ).toEqual(subject ? [{ type: 'email_sandbox', subject }] : [])
    })
})
