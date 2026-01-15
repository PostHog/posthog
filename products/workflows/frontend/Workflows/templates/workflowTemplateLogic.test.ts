import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { resetContext } from 'kea'
import { expectLogic, testUtilsPlugin } from 'kea-test-utils'

import api from 'lib/api'
import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'
import { HogFunctionTemplateType } from '~/types'

import { HogFlow, HogFlowAction } from '../hogflows/types'
import { workflowLogic } from '../workflowLogic'
import { workflowTemplateLogic } from './workflowTemplateLogic'
import { workflowTemplatesLogic } from './workflowTemplatesLogic'

jest.mock('lib/api', () => ({
    ...jest.requireActual('lib/api'),
    hogFlowTemplates: {
        createHogFlowTemplate: jest.fn(),
        updateHogFlowTemplate: jest.fn(),
        getHogFlowTemplate: jest.fn(),
    },
}))

jest.mock('lib/lemon-ui/LemonToast', () => ({
    lemonToast: {
        success: jest.fn(),
        error: jest.fn(),
    },
}))

const mockApi = api.hogFlowTemplates as jest.Mocked<typeof api.hogFlowTemplates>
const mockToast = require('lib/lemon-ui/LemonToast').lemonToast

describe('workflowTemplateLogic', () => {
    beforeEach(() => {
        initKeaTests()

        resetContext({
            plugins: [testUtilsPlugin],
        })

        jest.clearAllMocks()
    })

    describe('modal visibility', () => {
        it('should show modal when showSaveAsTemplateModal is called', async () => {
            const workflowLogicInstance = workflowLogic({ id: 'test-workflow-id' })
            workflowLogicInstance.mount()

            const logic = workflowTemplateLogic({ id: 'test-workflow-id' })
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.showSaveAsTemplateModal()
            })
                .toMatchValues({
                    saveAsTemplateModalVisible: true,
                })
                .toDispatchActions(['showSaveAsTemplateModal'])
        })

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
            const workflowLogicInstance = workflowLogic({ id: 'test-workflow-id' })
            workflowLogicInstance.mount()

            const logic = workflowTemplateLogic({ id: 'test-workflow-id' })
            logic.mount()

            // Set up workflow in workflowLogic
            const mockWorkflow: HogFlow = {
                id: 'test-workflow-id',
                team_id: 123,
                name: 'Test Workflow',
                description: 'Test Description',
                status: 'active',
                version: 1,
                created_at: '2024-01-01T00:00:00Z',
                updated_at: '2024-01-02T00:00:00Z',
                actions: [],
                edges: [],
                conversion: { window_minutes: 0, filters: [] },
                exit_condition: 'exit_only_at_end',
            }

            await expectLogic(workflowLogicInstance, () => {
                workflowLogicInstance.actions.loadWorkflowSuccess(mockWorkflow)
            })

            await expectLogic(workflowLogicInstance, () => {
                workflowLogicInstance.actions.loadHogFunctionTemplatesByIdSuccess({})
            })

            await expectLogic(logic, () => {
                logic.actions.showSaveAsTemplateModal()
            }).toMatchValues({
                saveAsTemplateModalVisible: true,
            })

            mockApi.createHogFlowTemplate.mockResolvedValue({ id: 'created-template-id' } as any)

            await expectLogic(logic, () => {
                logic.actions.setTemplateFormValue('name', 'Template Name')
                logic.actions.submitTemplateForm()
            })
                .toDispatchActions(['submitTemplateFormSuccess'])
                .toMatchValues({
                    saveAsTemplateModalVisible: false,
                })
        })

        it('should show error toast and hide modal when template load fails in edit mode', async () => {
            const workflowLogicInstance = workflowLogic({ id: 'test-workflow-id', editTemplateId: 'template-id' })
            workflowLogicInstance.mount()

            const mockWorkflow: HogFlow = {
                id: 'test-workflow-id',
                team_id: 123,
                name: 'Test Workflow',
                description: 'Test Description',
                status: 'draft',
                version: 1,
                created_at: '2024-01-01T00:00:00Z',
                updated_at: '2024-01-02T00:00:00Z',
                actions: [],
                edges: [],
                conversion: { window_minutes: 0, filters: [] },
                exit_condition: 'exit_only_at_end',
            }

            await expectLogic(workflowLogicInstance, () => {
                workflowLogicInstance.actions.loadWorkflowSuccess(mockWorkflow)
            })

            const logic = workflowTemplateLogic({ id: 'test-workflow-id', editTemplateId: 'template-id' })
            logic.mount()

            // Mock getHogFlowTemplate to fail
            mockApi.getHogFlowTemplate.mockRejectedValue(new Error('Template not found'))

            await expectLogic(logic, () => {
                logic.actions.showSaveAsTemplateModal()
            })
                .toDispatchActions(['showSaveAsTemplateModal', 'hideSaveAsTemplateModal'])
                .toMatchValues({
                    saveAsTemplateModalVisible: false,
                })

            expect(mockApi.getHogFlowTemplate).toHaveBeenCalledWith('template-id')
            expect(mockToast.error).toHaveBeenCalledWith('Template not found')
        })
    })

    describe('template form', () => {
        const mockHogFunctionTemplate: HogFunctionTemplateType = {
            id: 'test-template-id',
            name: 'Test Template',
            type: 'destination',
            code: '',
            code_language: 'hog',
            status: 'stable',
            free: true,
            inputs_schema: [
                {
                    key: 'url',
                    type: 'string',
                    label: 'URL',
                    required: true,
                    default: 'https://example.com',
                },
            ],
        }

        const createWorkflowWithFunctionAction = (): HogFlow => {
            return {
                id: 'test-workflow-id',
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
                        config: {
                            type: 'event',
                            filters: {},
                        },
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
                            inputs: {
                                url: { value: 'https://custom-url.com' },
                            },
                        },
                    },
                ],
                edges: [{ from: 'trigger_node', to: 'function-action-1', type: 'continue' }],
                conversion: { window_minutes: 0, filters: [] },
                exit_condition: 'exit_only_at_end',
            }
        }

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

        it('should create template with form values', async () => {
            const workflow = createWorkflowWithFunctionAction()
            const createdTemplate = { ...workflow, id: 'created-template-id' }

            mockApi.createHogFlowTemplate.mockResolvedValue(createdTemplate as any)

            // Load a staff user so scope: 'global' is allowed
            userLogic.mount()
            userLogic.actions.loadUserSuccess(MOCK_DEFAULT_USER)

            const workflowLogicInstance = workflowLogic({ id: 'test-workflow-id' })
            workflowLogicInstance.mount()

            const logic = workflowTemplateLogic({ id: 'test-workflow-id' })
            logic.mount()

            await expectLogic(workflowLogicInstance, () => {
                workflowLogicInstance.actions.loadWorkflowSuccess(workflow)
            })

            await expectLogic(workflowLogicInstance, () => {
                workflowLogicInstance.actions.loadHogFunctionTemplatesByIdSuccess({
                    'test-template-id': mockHogFunctionTemplate,
                })
            })

            await expectLogic(logic, () => {
                logic.actions.setTemplateFormValue('name', 'My Template')
                logic.actions.setTemplateFormValue('description', 'Template Description')
                logic.actions.setTemplateFormValue('image_url', 'https://example.com/image.png')
                logic.actions.setTemplateFormValue('scope', 'global')
                logic.actions.submitTemplateForm()
            }).toDispatchActions(['submitTemplateFormRequest', 'submitTemplateFormSuccess'])

            expect(mockApi.createHogFlowTemplate).toHaveBeenCalledTimes(1)
            const callArg = mockApi.createHogFlowTemplate.mock.calls[0][0]

            expect(callArg.name).toBe('My Template')
            expect(callArg.description).toBe('Template Description')
            expect(callArg.image_url).toBe('https://example.com/image.png')
            expect(callArg.scope).toBe('global')

            expect(mockToast.success).toHaveBeenCalledWith('Workflow template created')
        })

        it('should use workflow values as fallback when form values are empty', async () => {
            const workflow = createWorkflowWithFunctionAction()
            mockApi.createHogFlowTemplate.mockResolvedValue({ ...workflow, id: 'created-id' } as any)

            const workflowLogicInstance = workflowLogic({ id: 'test-workflow-id' })
            workflowLogicInstance.mount()

            const logic = workflowTemplateLogic({ id: 'test-workflow-id' })
            logic.mount()

            await expectLogic(workflowLogicInstance, () => {
                workflowLogicInstance.actions.loadWorkflowSuccess(workflow)
            })

            await expectLogic(workflowLogicInstance, () => {
                workflowLogicInstance.actions.loadHogFunctionTemplatesByIdSuccess({
                    'test-template-id': mockHogFunctionTemplate,
                })
            })

            // Submit with only name, empty description
            await expectLogic(logic, () => {
                logic.actions.setTemplateFormValue('name', 'Template Name')
                logic.actions.setTemplateFormValue('description', '')
                logic.actions.submitTemplateForm()
            })

            const callArg = mockApi.createHogFlowTemplate.mock.calls[0][0]
            expect(callArg.name).toBe('Template Name')
            expect(callArg.description).toBe('Test Description') // Falls back to workflow description
        })

        it('should preserve function action inputs when creating template', async () => {
            const workflow = createWorkflowWithFunctionAction()
            mockApi.createHogFlowTemplate.mockResolvedValue({ ...workflow, id: 'created-id' } as any)

            const workflowLogicInstance = workflowLogic({ id: 'test-workflow-id' })
            workflowLogicInstance.mount()

            const logic = workflowTemplateLogic({ id: 'test-workflow-id' })
            logic.mount()

            await expectLogic(workflowLogicInstance, () => {
                workflowLogicInstance.actions.loadWorkflowSuccess(workflow)
            })

            await expectLogic(workflowLogicInstance, () => {
                workflowLogicInstance.actions.loadHogFunctionTemplatesByIdSuccess({
                    'test-template-id': mockHogFunctionTemplate,
                })
            })

            await expectLogic(logic, () => {
                logic.actions.setTemplateFormValue('name', 'Template')
                logic.actions.submitTemplateForm()
            })

            const callArg = mockApi.createHogFlowTemplate.mock.calls[0][0]
            const functionAction = callArg.actions?.find(
                (a: HogFlowAction) => a.id === 'function-action-1' && a.type === 'function'
            )
            if (functionAction && 'inputs' in functionAction.config) {
                expect(functionAction.config.inputs).toEqual({
                    url: { value: 'https://custom-url.com' },
                })
            }
        })

        it('should default scope to team when not provided', async () => {
            const workflow = createWorkflowWithFunctionAction()
            mockApi.createHogFlowTemplate.mockResolvedValue({ ...workflow, id: 'created-id' } as any)

            const workflowLogicInstance = workflowLogic({ id: 'test-workflow-id' })
            workflowLogicInstance.mount()

            const logic = workflowTemplateLogic({ id: 'test-workflow-id' })
            logic.mount()

            await expectLogic(workflowLogicInstance, () => {
                workflowLogicInstance.actions.loadWorkflowSuccess(workflow)
            })

            await expectLogic(workflowLogicInstance, () => {
                workflowLogicInstance.actions.loadHogFunctionTemplatesByIdSuccess({
                    'test-template-id': mockHogFunctionTemplate,
                })
            })

            await expectLogic(logic, () => {
                logic.actions.setTemplateFormValue('name', 'Template')
                // Don't set scope, should default to 'team'
                logic.actions.submitTemplateForm()
            })

            const callArg = mockApi.createHogFlowTemplate.mock.calls[0][0]
            expect(callArg.scope).toBe('team')
        })
    })

    describe('update template', () => {
        const createWorkflow = (): HogFlow => ({
            id: 'test-workflow-id',
            team_id: 123,
            name: 'Updated Workflow',
            description: 'Updated Description',
            status: 'draft',
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
                    config: {
                        type: 'event',
                        filters: {},
                    },
                },
            ],
            edges: [],
            conversion: { window_minutes: 0, filters: [] },
            exit_condition: 'exit_only_at_end',
        })

        it('should update template, reload workflow, and reload template list', async () => {
            const workflow = createWorkflow()
            const updatedTemplate = { ...workflow, id: 'template-id', scope: 'team' as const }
            mockApi.updateHogFlowTemplate.mockResolvedValue(updatedTemplate)
            mockApi.getHogFlowTemplate.mockResolvedValue(updatedTemplate)

            // Use id: 'new' so loadWorkflow calls getHogFlowTemplate when editTemplateId is set
            const workflowLogicInstance = workflowLogic({ id: 'new', editTemplateId: 'template-id' })
            workflowLogicInstance.mount()
            await expectLogic(workflowLogicInstance, () => {
                workflowLogicInstance.actions.loadWorkflowSuccess(workflow)
            })

            const templatesLogic = workflowTemplatesLogic()
            templatesLogic.mount()

            const templateLogic = workflowTemplateLogic({ id: 'new', editTemplateId: 'template-id' })
            templateLogic.mount()

            const workflowTemplate = { ...workflow, id: 'template-id' }
            await expectLogic(workflowLogicInstance, () => {
                templateLogic.actions.updateTemplate(workflowTemplate)
            }).toDispatchActions(['loadWorkflow', 'loadWorkflowSuccess'])

            // Verify API call with correct data
            expect(mockApi.updateHogFlowTemplate).toHaveBeenCalledWith(
                'template-id',
                expect.objectContaining({
                    name: 'Updated Workflow',
                    description: 'Updated Description',
                    actions: expect.any(Array),
                    edges: expect.any(Array),
                    conversion: expect.any(Object),
                    exit_condition: 'exit_only_at_end',
                })
            )

            // Verify workflow reload
            expect(mockApi.getHogFlowTemplate).toHaveBeenCalledWith('template-id')

            // Verify template list reload
            await expectLogic(templatesLogic).toDispatchActions(['loadWorkflowTemplates'])

            expect(mockToast.success).toHaveBeenCalledWith('Template updated')
        })
    })
})
