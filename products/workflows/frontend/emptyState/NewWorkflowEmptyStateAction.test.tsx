import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { Provider } from 'kea'
import { router } from 'kea-router'
import { type Action, expectLogic } from 'kea-test-utils'

import api from 'lib/api'
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

import { workflowsEmptyState } from './workflowsEmptyState'

const AI_FIRST_FLAGS = [
    FEATURE_FLAGS.WORKFLOWS_AI_FIRST_NEW,
    FEATURE_FLAGS.PHAI_SCENE_AUTO_OPEN,
    FEATURE_FLAGS.PHAI_SANDBOX_MODE,
]

function grantWorkflowAccess(level: AccessControlLevel): void {
    window.POSTHOG_APP_CONTEXT = {
        ...window.POSTHOG_APP_CONTEXT,
        resource_access_control: { [AccessControlResourceType.Workflow]: level },
    } as AppContext
}

function renderFirstRunEmptyState(): void {
    render(
        <Provider>
            <ProductEmptyState config={workflowsEmptyState.config} mode="needs-setup" />
        </Provider>
    )
}

function isPrimaryActionClick(action: Action): boolean {
    return (
        action.type ===
            productSetupStatusLogic({ productKey: ProductKey.WORKFLOWS }).actionTypes.reportSetupInteraction &&
        action.payload.action === 'primary action clicked'
    )
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
                '/api/projects/:team_id/hog_flow_templates/': { count: 0, results: [] },
            },
            patch: {
                // nosemgrep: no-environments-api-urls-frontend -- add_product_intent is env-scoped, so the msw mock must match /api/environments to intercept it
                '/api/environments/:team_id/add_product_intent': {},
            },
        })
        initKeaTests()
        router.actions.push('/workflows', {}, {})
    })

    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
    })

    it.each([
        {
            variant: 'outside the AI-first experiment',
            flags: [],
            opens: 'the template chooser',
            chooserOpen: true,
            path: '/workflows',
            searchParams: {},
        },
        {
            variant: 'in the AI-first experiment',
            flags: AI_FIRST_FLAGS,
            opens: 'the AI composer',
            chooserOpen: false,
            path: '/workflows/new/workflow',
            searchParams: { mode: 'ai' },
        },
    ])(
        'opens $opens on the first run $variant without reporting workflow creation',
        async ({ flags, chooserOpen, path, searchParams }) => {
            const productIntentRequest = jest.spyOn(api.productIntents, 'update')
            grantWorkflowAccess(AccessControlLevel.Editor)
            featureFlagLogic.actions.setFeatureFlags(flags, Object.fromEntries(flags.map((flag) => [flag, true])))
            const setupStatus = productSetupStatusLogic({ productKey: ProductKey.WORKFLOWS })
            setupStatus.mount()
            renderFirstRunEmptyState()

            await expectLogic(setupStatus, () => {
                fireEvent.click(screen.getByText('New workflow'))
            }).toDispatchActions([isPrimaryActionClick])

            expect(screen.queryByText('Create a workflow') !== null).toBe(chooserOpen)
            expect(removeProjectIdIfPresent(router.values.location.pathname)).toBe(path)
            expect(router.values.searchParams).toEqual(searchParams)
            expect(productIntentRequest).not.toHaveBeenCalled()
        }
    )

    it('blocks the first-run button for a person without editor access', async () => {
        grantWorkflowAccess(AccessControlLevel.Viewer)
        const setupStatus = productSetupStatusLogic({ productKey: ProductKey.WORKFLOWS })
        setupStatus.mount()
        renderFirstRunEmptyState()

        await expectLogic(setupStatus, () => {
            fireEvent.click(screen.getByText('New workflow'))
        }).toNotHaveDispatchedActions([isPrimaryActionClick])

        expect(screen.queryByText('Create a workflow')).not.toBeInTheDocument()
        expect(removeProjectIdIfPresent(router.values.location.pathname)).toBe('/workflows')
    })
})
