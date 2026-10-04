import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { ProductEmptyState } from 'lib/components/ProductEmptyState/ProductEmptyState'
import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { maxMocks } from 'scenes/max/testUtils'

import { useMocks } from '~/mocks/jest'
import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, type AppContext } from '~/types'

import type { HogFlowTemplate } from '../Workflows/hogflows/types'
import { workflowsEmptyState } from './workflowsEmptyState'

const WELCOME_TEMPLATE: HogFlowTemplate = {
    id: 'tpl-welcome',
    team_id: 1,
    version: 1,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    name: 'Welcome email sequence',
    description: 'Welcome new signups.',
    tags: [],
    scope: 'global',
    actions: [
        {
            id: 'trigger_node',
            type: 'trigger',
            name: 'Trigger',
            description: '',
            created_at: 0,
            updated_at: 0,
            config: { type: 'event', filters: {} },
        },
        {
            id: 'exit_node',
            type: 'exit',
            name: 'Exit',
            description: '',
            created_at: 0,
            updated_at: 0,
            config: { reason: 'Default exit' },
        },
    ],
    edges: [{ from: 'trigger_node', to: 'exit_node', type: 'continue' }],
    trigger: { type: 'event', filters: {} },
    exit_condition: 'exit_only_at_end',
}

const AI_FIRST_FLAGS = [
    FEATURE_FLAGS.WORKFLOWS_AI_FIRST_NEW,
    FEATURE_FLAGS.PHAI_SCENE_AUTO_OPEN,
    FEATURE_FLAGS.PHAI_SANDBOX_MODE,
]

function grantWorkflowEditorAccess(): void {
    window.POSTHOG_APP_CONTEXT = {
        ...window.POSTHOG_APP_CONTEXT,
        resource_access_control: { [AccessControlResourceType.Workflow]: AccessControlLevel.Editor },
    } as AppContext
}

describe('NewWorkflowEmptyStateAction', () => {
    beforeEach(() => {
        useMocks({
            ...maxMocks,
            get: {
                ...maxMocks.get,
                '/_preflight/': { cloud: false },
                '/api/environments/@current/': {},
                '/api/users/@me/': {},
                '/api/projects/:team_id/hog_flow_templates/': { count: 1, results: [WELCOME_TEMPLATE] },
            },
            patch: {
                // nosemgrep: no-environments-api-urls-frontend -- add_product_intent is env-scoped, so the msw mock must match /api/environments to intercept it
                '/api/environments/:team_id/add_product_intent': {},
            },
        })
        initKeaTests()
        grantWorkflowEditorAccess()
        router.actions.push('/workflows', {}, {})
    })

    afterEach(() => {
        cleanup()
    })

    it.each([
        {
            variant: 'outside the AI-first experiment',
            flags: [],
            opens: 'the template chooser',
            showsTemplates: true,
            path: '/workflows',
            searchParams: {},
        },
        {
            variant: 'in the AI-first experiment',
            flags: AI_FIRST_FLAGS,
            opens: 'the AI composer',
            showsTemplates: false,
            path: '/workflows/new/workflow',
            searchParams: { mode: 'ai' },
        },
    ])(
        'opens $opens on the first run $variant and counts the click',
        async ({ flags, showsTemplates, path, searchParams }) => {
            featureFlagLogic.actions.setFeatureFlags(flags, Object.fromEntries(flags.map((flag) => [flag, true])))
            const setupStatus = productSetupStatusLogic({ productKey: ProductKey.WORKFLOWS })
            setupStatus.mount()
            render(
                <Provider>
                    <ProductEmptyState config={workflowsEmptyState.config} mode="needs-setup" />
                </Provider>
            )

            await expectLogic(setupStatus, () => {
                fireEvent.click(screen.getByText('New workflow'))
            }).toDispatchActions([
                (action) =>
                    action.type === setupStatus.actionTypes.reportSetupInteraction &&
                    action.payload.action === 'primary action clicked',
            ])

            await waitFor(() => expect(screen.queryByText('Welcome email sequence') !== null).toBe(showsTemplates))
            expect(removeProjectIdIfPresent(router.values.location.pathname)).toBe(path)
            expect(router.values.searchParams).toEqual(searchParams)
        }
    )
})
