import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { render, screen, waitFor } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'
import { createElement } from 'react'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { MockResolverInfo } from '~/mocks/utils'
import { initKeaTests } from '~/test/init'
import { UserType } from '~/types'

import { HogFlow, HogFlowTemplate } from '../hogflows/types'
import { workflowLogic } from '../workflowLogic'
import { workflowTemplateLogic } from './workflowTemplateLogic'
import { workflowTemplatesLogic } from './workflowTemplatesLogic'

const WORKFLOW_ID = 'test-workflow-id'

const makeWorkflow = (): HogFlow => ({
    id: WORKFLOW_ID,
    team_id: 123,
    name: 'Test Workflow',
    description: 'Test Description',
    status: 'active',
    version: 1,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-02T00:00:00Z',
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
            id: 'function-action-1',
            type: 'function',
            name: 'Function Action',
            description: '',
            created_at: 1000,
            updated_at: 2000,
            config: {
                template_id: 'test-template-id',
                template_uuid: 'test-uuid',
                inputs: { url: { value: 'https://custom-url.com' } },
            },
        },
    ],
    edges: [{ from: 'trigger_node', to: 'function-action-1', type: 'continue' }],
    conversion: { filters: [] },
    exit_condition: 'exit_only_at_end',
})

describe('workflowTemplateLogic', () => {
    let templates: Record<string, HogFlowTemplate>
    let currentUser: UserType

    const findTemplate = ({ params }: MockResolverInfo): HogFlowTemplate | undefined => templates[String(params.id)]

    const showToasts = (): void => {
        lemonToast.dismiss()
        render(createElement(jest.requireActual('react-toastify').ToastContainer))
    }

    const loadWorkflow = async (props: { id: string; editTemplateId?: string }): Promise<void> => {
        const workflowLogicInstance = workflowLogic(props)
        workflowLogicInstance.mount()
        await waitFor(() => expect(workflowLogicInstance.values.originalWorkflow).not.toBeNull())
    }

    const loadUser = async (user: UserType): Promise<void> => {
        currentUser = user
        userLogic.mount()
        userLogic.actions.loadUser()
        await waitFor(() => expect(userLogic.values.user?.is_staff).toBe(user.is_staff))
    }

    const submit = async (
        logic: ReturnType<typeof workflowTemplateLogic.build>,
        values: Parameters<typeof logic.actions.setTemplateFormValues>[0]
    ): Promise<void> => {
        await expectLogic(logic, () => {
            logic.actions.setTemplateFormValues(values)
            logic.actions.submitTemplateForm()
        }).toFinishAllListeners()
    }

    const storedTemplate = (): HogFlowTemplate => {
        expect(Object.keys(templates)).toHaveLength(1)
        return Object.values(templates)[0]
    }

    beforeEach(() => {
        templates = {}
        currentUser = MOCK_DEFAULT_USER
        useMocks({
            get: {
                '/api/users/@me/': () => [200, currentUser],
                '/api/environments/:team_id/hog_flows/:id/': makeWorkflow(),
                '/api/projects/:team_id/hog_function_templates/': { results: [], count: 0 },
                '/api/projects/:team_id/hog_flow_templates/': () => [
                    200,
                    { results: Object.values(templates), count: Object.keys(templates).length },
                ],
                '/api/projects/:team_id/hog_flow_templates/:id/': (info) => {
                    const template = findTemplate(info)
                    return template ? [200, template] : [404, { detail: 'Not found.' }]
                },
            },
            post: {
                '/api/projects/:team_id/hog_flow_templates/': async ({ request }) => {
                    const id = `created-template-${Object.keys(templates).length + 1}`
                    templates[id] = { ...((await request.json()) as HogFlowTemplate), id }
                    return [201, templates[id]]
                },
            },
            patch: {
                '/api/projects/:team_id/hog_flow_templates/:id/': async (info) => {
                    const template = findTemplate(info)
                    if (!template) {
                        return [404, { detail: 'Not found.' }]
                    }
                    Object.assign(template, await info.request.json())
                    return [200, template]
                },
            },
        })
        initKeaTests()
    })

    describe('modal visibility', () => {
        it('should hide modal when hideSaveAsTemplateModal is called', async () => {
            const workflowLogicInstance = workflowLogic({ id: 'test-workflow-id' })
            workflowLogicInstance.mount()

            const logic = workflowTemplateLogic({ id: 'test-workflow-id' })
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.showSaveAsTemplateModal()
            }).toMatchValues({
                saveAsTemplateModalVisible: true,
            })

            await expectLogic(logic, () => {
                logic.actions.hideSaveAsTemplateModal()
            })
                .toMatchValues({
                    saveAsTemplateModalVisible: false,
                })
                .toDispatchActions(['hideSaveAsTemplateModal'])
        })

        it('should hide modal when template form is submitted successfully', async () => {
            await loadWorkflow({ id: WORKFLOW_ID })
            const logic = workflowTemplateLogic({ id: WORKFLOW_ID })
            logic.mount()

            logic.actions.showSaveAsTemplateModal()
            expect(logic.values.saveAsTemplateModalVisible).toBe(true)

            await submit(logic, { name: 'Template Name' })

            expect(logic.values.saveAsTemplateModalVisible).toBe(false)
        })

        it('should show error toast and hide modal when template load fails in edit mode', async () => {
            showToasts()
            await loadWorkflow({ id: WORKFLOW_ID, editTemplateId: 'template-id' })
            const logic = workflowTemplateLogic({ id: WORKFLOW_ID, editTemplateId: 'template-id' })
            logic.mount()

            logic.actions.showSaveAsTemplateModal()

            expect(await screen.findByText('Not found.')).toBeTruthy()
            expect(logic.values.saveAsTemplateModalVisible).toBe(false)
        })
    })

    describe('template form', () => {
        it('should validate template form name is required', async () => {
            const workflowLogicInstance = workflowLogic({ id: 'test-workflow-id' })
            workflowLogicInstance.mount()

            const logic = workflowTemplateLogic({ id: 'test-workflow-id' })
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.setTemplateFormValue('name', '')
                logic.actions.touchTemplateFormField('name')
            }).toMatchValues({
                templateForm: expect.objectContaining({
                    name: '',
                }),
                isTemplateFormValid: false,
            })
        })

        it.each([
            { isStaff: true, storedScope: 'global' },
            { isStaff: false, storedScope: 'team' },
        ])(
            'should create the template from the workflow and form values (staff: $isStaff)',
            async ({ isStaff, storedScope }) => {
                showToasts()
                await loadUser({ ...MOCK_DEFAULT_USER, is_staff: isStaff })
                await loadWorkflow({ id: WORKFLOW_ID })
                const logic = workflowTemplateLogic({ id: WORKFLOW_ID })
                logic.mount()

                await submit(logic, {
                    name: 'My Template',
                    description: 'Template Description',
                    image_url: 'https://example.com/image.png',
                    scope: 'global',
                })

                const workflow = makeWorkflow()
                expect(storedTemplate()).toMatchObject({
                    name: 'My Template',
                    description: 'Template Description',
                    image_url: 'https://example.com/image.png',
                    scope: storedScope,
                    actions: workflow.actions,
                    edges: workflow.edges,
                })
                expect(await screen.findByText('Workflow template created')).toBeTruthy()
            }
        )

        it('should use workflow values as fallback when form values are empty', async () => {
            await loadWorkflow({ id: WORKFLOW_ID })
            const logic = workflowTemplateLogic({ id: WORKFLOW_ID })
            logic.mount()

            await submit(logic, { name: 'Template Name', description: '' })

            expect(storedTemplate()).toMatchObject({ name: 'Template Name', description: 'Test Description' })
        })

        it('should default scope to team when not provided', async () => {
            await loadWorkflow({ id: WORKFLOW_ID })
            const logic = workflowTemplateLogic({ id: WORKFLOW_ID })
            logic.mount()

            await submit(logic, { name: 'Template' })

            expect(storedTemplate().scope).toBe('team')
        })
    })

    describe('update template', () => {
        it('should update template, reload workflow, and reload template list', async () => {
            templates['template-id'] = {
                ...makeWorkflow(),
                id: 'template-id',
                name: 'Original template',
                scope: 'team',
                tags: [],
            }
            showToasts()
            const props = { id: 'new', editTemplateId: 'template-id' }
            await loadWorkflow(props)
            const templatesLogic = workflowTemplatesLogic()
            templatesLogic.mount()
            await waitFor(() => expect(templatesLogic.values.workflowTemplates).toHaveLength(1))
            const templateLogic = workflowTemplateLogic(props)
            templateLogic.mount()

            templateLogic.actions.showSaveAsTemplateModal()
            await waitFor(() => expect(templateLogic.values.templateForm.name).toBe('Original template'))
            await submit(templateLogic, { name: 'Renamed template' })

            expect(await screen.findByText('Template updated')).toBeTruthy()
            await waitFor(() => expect(workflowLogic(props).values.workflow.name).toBe('Renamed template'))
            await waitFor(() =>
                expect(templatesLogic.values.workflowTemplates.map(({ name }) => name)).toEqual(['Renamed template'])
            )
        })
    })
})
