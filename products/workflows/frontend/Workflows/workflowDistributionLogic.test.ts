import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { workflowDistributionLogic } from './workflowDistributionLogic'
import { NEW_WORKFLOW, workflowLogic } from './workflowLogic'

Object.defineProperty(posthog, 'getGroups', { value: jest.fn(), configurable: true })

describe('authorized browser offer-to-saved-draft', () => {
    let distribution: ReturnType<typeof workflowDistributionLogic.build>
    let creates: number
    const source = {
        projectUuid: MOCK_DEFAULT_TEAM.uuid,
        placementId: 'selected-event' as const,
        sourceActionId: 'event-definition-42',
        eligible: true,
        trigger: {
            type: 'event' as const,
            filters: { events: [{ id: 'workspace_joined', name: 'workspace_joined', type: 'events' as const }] },
        },
    }

    beforeEach(() => {
        localStorage.clear()
        creates = 0
        useMocks({
            get: { '/api/projects/:team_id/hog_function_templates/': { results: [], count: 0 } },
            post: {
                '/api/environments/:team_id/hog_flows/': () => {
                    creates += 1
                    return [201, { ...NEW_WORKFLOW, id: '7e778826-9987-4205-bb5d-005f4ab33c10' }]
                },
            },
        })
        initKeaTests()
        jest.mocked(posthog.get_property).mockReset()
        jest.mocked(posthog.capture).mockClear()
        window.POSTHOG_APP_CONTEXT!.resource_access_control = Object.fromEntries(
            Object.values(AccessControlResourceType).map((resource) => [resource, AccessControlLevel.Editor])
        ) as Record<AccessControlResourceType, AccessControlLevel>
        jest.spyOn(posthog, 'getGroups').mockReturnValue({ project: MOCK_DEFAULT_TEAM.uuid })
        jest.spyOn(posthog, 'getFeatureFlagResult').mockImplementation((key) => ({
            key,
            enabled: true,
            variant: key === 'workflows-distribution' ? 'offer' : undefined,
            payload: undefined,
        }))
        jest.spyOn(posthog, 'capture')
        distribution = workflowDistributionLogic()
        distribution.mount()
    })

    afterEach(() => jest.restoreAllMocks())

    it.each([
        'unavailable',
        'off',
        'unknown',
        'overridden',
        'placement off',
        'denied',
        'ineligible',
        'different UUID',
        'wrong assignment UUID',
    ])('does not enroll when %s', async (reason) => {
        if (reason === 'unavailable') {
            jest.mocked(posthog.getFeatureFlagResult).mockReturnValue(undefined)
        } else if (reason === 'off' || reason === 'unknown' || reason === 'placement off') {
            jest.mocked(posthog.getFeatureFlagResult).mockImplementation((key) => ({
                key,
                enabled: !(reason === 'off' || (reason === 'placement off' && key !== 'workflows-distribution')),
                variant: key === 'workflows-distribution' ? (reason === 'unknown' ? 'unexpected' : 'offer') : undefined,
                payload: undefined,
            }))
        } else if (reason === 'overridden') {
            jest.spyOn(posthog, 'get_property').mockImplementation((key) =>
                key === '$override_feature_flags' ? { 'workflows-distribution': 'control' } : undefined
            )
        } else if (reason === 'denied') {
            window.POSTHOG_APP_CONTEXT!.resource_access_control.hog_flow = AccessControlLevel.Viewer
        } else if (reason === 'wrong assignment UUID') {
            jest.mocked(posthog.getGroups).mockReturnValue({ project: 'another-project-uuid' })
        }
        await expectLogic(distribution, () =>
            distribution.actions.offer({
                ...source,
                eligible: reason !== 'ineligible',
                projectUuid: reason === 'different UUID' ? 'another-project-uuid' : source.projectUuid,
            })
        ).toFinishAllListeners()
        expect(Object.values(distribution.values.offers)).toHaveLength(0)
        expect(
            jest.mocked(posthog.capture).mock.calls.filter(([event]) => event.startsWith('workflow distribution'))
        ).toHaveLength(0)
    })

    it('remembers dismissal locally while a new source action and project remain independent', async () => {
        await expectLogic(distribution, () => distribution.actions.offer(source)).toFinishAllListeners()
        distribution.actions.dismiss(Object.values(distribution.values.offers)[0].contextKey)
        distribution.unmount()
        distribution = workflowDistributionLogic()
        distribution.mount()
        await expectLogic(distribution, () => distribution.actions.offer(source)).toFinishAllListeners()
        expect(Object.values(distribution.values.offers)).toHaveLength(0)
        await expectLogic(distribution, () =>
            distribution.actions.offer({ ...source, sourceActionId: 'event-definition-43' })
        ).toFinishAllListeners()
        expect(Object.values(distribution.values.offers)).toHaveLength(1)
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, id: 998, uuid: 'another-project-uuid' })
        expect(Object.values(distribution.values.offers)).toHaveLength(0)
        jest.mocked(posthog.getGroups).mockReturnValue({ project: 'another-project-uuid' })
        await expectLogic(distribution, () =>
            distribution.actions.offer({ ...source, projectUuid: 'another-project-uuid' })
        ).toFinishAllListeners()
        expect(Object.values(distribution.values.offers)).toHaveLength(1)
    })

    it('records zero-click control eligibility for the assigned project UUID without exposure or navigation', async () => {
        jest.mocked(posthog.getFeatureFlagResult).mockImplementation((key) => ({
            key,
            enabled: true,
            variant: key === 'workflows-distribution' ? 'control' : undefined,
            payload: undefined,
        }))
        router.actions.push('/events')
        await expectLogic(distribution, () => distribution.actions.offer(source)).toFinishAllListeners()
        expect(Object.values(distribution.values.offers)).toHaveLength(0)
        expect(removeProjectIdIfPresent(router.values.location.pathname)).toBe('/events')
        expect(creates).toBe(0)
        expect(posthog.capture).toHaveBeenCalledWith(
            'workflow distribution eligible',
            expect.objectContaining({
                project_uuid: MOCK_DEFAULT_TEAM.uuid,
                arm: 'control',
                placement_id: 'selected-event',
            })
        )
        expect(
            jest.mocked(posthog.capture).mock.calls.filter(([event]) => event.startsWith('workflow distribution'))
        ).toHaveLength(1)
    })

    it('opens an unsaved inactive exact-event editor and associates only its successful create', async () => {
        await expectLogic(distribution, () => distribution.actions.offer(source)).toFinishAllListeners()
        const offer = Object.values(distribution.values.offers)[0]
        expect(offer).toBeTruthy()
        distribution.actions.offerShown(offer.contextKey)
        await expectLogic(distribution, () => distribution.actions.open(offer.contextKey)).toFinishAllListeners()
        expect(removeProjectIdIfPresent(router.values.location.pathname)).toBe('/workflows/new/workflow')
        const editor = workflowLogic({
            id: 'new',
            triggerPrefill: router.values.searchParams.trigger as string,
            distributionContextKey: router.values.searchParams.distributionContext as string,
        })
        editor.mount()
        await expectLogic(editor).toDispatchActions(['loadWorkflowSuccess'])
        expect(creates).toBe(0)
        expect(editor.values.workflow.status).toBe('draft')
        expect(editor.values.workflow.actions.find((action) => action.type === 'trigger')?.config).toEqual(
            source.trigger
        )
        const backgroundEditor = workflowLogic({ id: 'new' })
        backgroundEditor.mount()
        await expectLogic(backgroundEditor).toDispatchActions(['loadWorkflowSuccess'])
        editor.actions.setWorkflowValue('name', 'Workspace follow-up')
        teamLogic.actions.loadCurrentTeamSuccess(MOCK_DEFAULT_TEAM)
        await expectLogic(editor, () => editor.actions.saveWorkflow(editor.values.workflow)).toDispatchActions([
            'saveWorkflowSuccess',
        ])
        expect(creates).toBe(1)
        expect(posthog.capture).toHaveBeenCalledWith(
            'workflow distribution draft created',
            expect.objectContaining({
                project_uuid: MOCK_DEFAULT_TEAM.uuid,
                placement_id: 'selected-event',
                arm: 'offer',
                workflow_id: '7e778826-9987-4205-bb5d-005f4ab33c10',
            })
        )
        await expectLogic(editor, () => editor.actions.duplicate()).toFinishAllListeners()
        expect(creates).toBe(2)
        expect(
            jest.mocked(posthog.capture).mock.calls.filter(([event]) => event === 'workflow distribution draft created')
        ).toHaveLength(1)
        await expectLogic(distribution, () => distribution.actions.offer(source)).toFinishAllListeners()
        expect(Object.values(distribution.values.offers)).toHaveLength(0)
        editor.unmount()
        backgroundEditor.unmount()
        distribution.unmount()
        distribution = workflowDistributionLogic()
        distribution.mount()
        await expectLogic(distribution, () => distribution.actions.offer(source)).toFinishAllListeners()
        expect(Object.values(distribution.values.offers)).toHaveLength(0)
        const unrelated = workflowLogic({ id: 'new' })
        unrelated.mount()
        await expectLogic(unrelated).toDispatchActions(['loadWorkflowSuccess'])
        await expectLogic(unrelated, () => unrelated.actions.saveWorkflow(unrelated.values.workflow)).toDispatchActions(
            ['saveWorkflowSuccess']
        )
        expect(creates).toBe(3)
        expect(
            jest.mocked(posthog.capture).mock.calls.filter(([event]) => event === 'workflow distribution draft created')
        ).toHaveLength(1)
    })

    it('never retries an uncertain create or attributes a later manual retry', async () => {
        useMocks({
            post: {
                '/api/environments/:team_id/hog_flows/': () => {
                    creates += 1
                    return [500, { detail: 'Response unavailable' }]
                },
            },
        })
        await expectLogic(distribution, () => distribution.actions.offer(source)).toFinishAllListeners()
        await expectLogic(distribution, () =>
            distribution.actions.open(Object.values(distribution.values.offers)[0].contextKey)
        ).toFinishAllListeners()
        const editor = workflowLogic({
            id: 'new',
            triggerPrefill: router.values.searchParams.trigger as string,
            distributionContextKey: router.values.searchParams.distributionContext as string,
        })
        editor.mount()
        await expectLogic(editor).toDispatchActions(['loadWorkflowSuccess'])
        await expectLogic(editor, () => editor.actions.saveWorkflow(editor.values.workflow)).toDispatchActions([
            'saveWorkflowFailure',
        ])
        expect(creates).toBe(1)
        expect(
            jest.mocked(posthog.capture).mock.calls.filter(([event]) => event === 'workflow distribution draft created')
        ).toHaveLength(0)
        useMocks({
            post: {
                '/api/environments/:team_id/hog_flows/': () => {
                    creates += 1
                    return [201, { ...NEW_WORKFLOW, id: 'manual-retry-workflow' }]
                },
            },
        })
        await expectLogic(editor, () => editor.actions.saveWorkflow(editor.values.workflow)).toDispatchActions([
            'saveWorkflowSuccess',
        ])
        expect(creates).toBe(2)
        expect(
            jest.mocked(posthog.capture).mock.calls.filter(([event]) => event === 'workflow distribution draft created')
        ).toHaveLength(0)
    })
})
