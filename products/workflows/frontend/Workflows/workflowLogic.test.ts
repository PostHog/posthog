import { resetContext } from 'kea'
import { expectLogic, testUtilsPlugin } from 'kea-test-utils'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { initKeaTests } from '~/test/init'
import { HogFunctionTemplateType } from '~/types'

import { HogFlow, HogFlowAction } from './hogflows/types'
import { workflowLogic } from './workflowLogic'

jest.mock('lib/api', () => ({
    ...jest.requireActual('lib/api'),
    hogFlowTemplates: {
        createHogFlowTemplate: jest.fn(),
    },
}))

jest.mock('lib/lemon-ui/LemonToast', () => ({
    lemonToast: {
        success: jest.fn(),
    },
}))

const mockApi = api.hogFlowTemplates as jest.Mocked<typeof api.hogFlowTemplates>
const mockToast = lemonToast as jest.Mocked<typeof lemonToast>

describe('workflowLogic', () => {
    beforeEach(() => {
        initKeaTests()

        resetContext({
            plugins: [testUtilsPlugin],
        })

        jest.clearAllMocks()
    })

    describe('saveAsTemplate', () => {
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
                {
                    key: 'method',
                    type: 'string',
                    label: 'Method',
                    required: false,
                    default: 'POST',
                },
                {
                    key: 'custom_input',
                    type: 'string',
                    label: 'Custom Input',
                    required: false,
                    // No default - should not be included
                },
            ],
        }

        const createWorkflowWithFunctionAction = (): HogFlow => {
            return {
                id: 'test-workflow-id',
                team_id: 123,
                name: 'Test Workflow',
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
                                url: { value: 'https://custom-url.com' }, // Custom value, should be reset to default
                                method: { value: 'GET' }, // Custom value, should be reset to default
                                custom_input: { value: 'custom' }, // No default in template, should be removed
                            },
                        },
                    },
                    {
                        id: 'exit_node',
                        type: 'exit',
                        name: 'Exit',
                        description: '',
                        created_at: 0,
                        updated_at: 0,
                        config: {
                            reason: 'Default exit',
                        },
                    },
                ],
                edges: [
                    { from: 'trigger_node', to: 'function-action-1', type: 'continue' },
                    { from: 'function-action-1', to: 'exit_node', type: 'continue' },
                ],
                conversion: { window_minutes: 0, filters: [] },
                exit_condition: 'exit_only_at_end',
            }
        }

        it('should call createHogFlowTemplate with properly sanitized template', async () => {
            const workflow = createWorkflowWithFunctionAction()
            const createdTemplate = { ...workflow, id: 'created-template-id' }

            mockApi.createHogFlowTemplate.mockResolvedValue(createdTemplate as any)

            const logic = workflowLogic({ id: 'test-workflow-id' })
            logic.mount()

            // Load templates first
            await expectLogic(logic, () => {
                ;(logic.actions as any).loadHogFunctionTemplatesByIdSuccess({
                    'test-template-id': mockHogFunctionTemplate,
                })
            })

            // Set the original workflow
            await expectLogic(logic, () => {
                logic.actions.loadWorkflowSuccess(workflow)
            }).toDispatchActions(['loadWorkflowSuccess', 'resetWorkflow'])

            // Call saveAsTemplate
            await expectLogic(logic, () => {
                ;(logic.actions as any).saveAsTemplate()
            }).toDispatchActions(['saveAsTemplate'])

            // Verify API was called with sanitized template
            expect(mockApi.createHogFlowTemplate).toHaveBeenCalledTimes(1)
            const callArg = mockApi.createHogFlowTemplate.mock.calls[0][0]

            // Verify metadata fields are removed
            expect(callArg).not.toHaveProperty('id')
            expect(callArg).not.toHaveProperty('team_id')
            expect(callArg).not.toHaveProperty('created_at')
            expect(callArg).not.toHaveProperty('updated_at')

            // Verify status is set to template
            expect(callArg.status).toBe('template')

            // Verify name is preserved
            expect(callArg.name).toBe('Test Workflow')

            // Verify function action inputs are reset to defaults
            const functionAction = callArg.actions?.find(
                (a: HogFlowAction) => a.id === 'function-action-1' && a.type === 'function'
            )
            if (functionAction && 'inputs' in functionAction.config) {
                expect(functionAction.config.inputs).toEqual({
                    url: { value: 'https://example.com' }, // Reset to default
                    method: { value: 'POST' }, // Reset to default
                    // custom_input should not be present since it has no default
                })
                expect(functionAction.config.inputs).not.toHaveProperty('custom_input')
            }

            // Verify non-function actions are unchanged
            const triggerAction = callArg.actions?.find((a: HogFlowAction) => a.id === 'trigger_node')
            if (triggerAction && 'type' in triggerAction.config) {
                expect(triggerAction.config).toEqual({
                    type: 'event',
                    filters: {},
                })
            }

            // Verify toast is shown
            expect(mockToast.success).toHaveBeenCalledWith('Workflow template created')
        })

        it('should not call API if originalWorkflow is null', async () => {
            const logic = workflowLogic({ id: 'new' })
            logic.mount()

            await expectLogic(logic, () => {
                ;(logic.actions as any).saveAsTemplate()
            }).toDispatchActions(['saveAsTemplate'])

            expect(mockApi.createHogFlowTemplate).not.toHaveBeenCalled()
            expect(mockToast.success).not.toHaveBeenCalled()
        })

        it('should handle workflow with multiple function actions', async () => {
            const baseWorkflow = createWorkflowWithFunctionAction()
            const workflow: HogFlow = {
                ...baseWorkflow,
                actions: [
                    ...baseWorkflow.actions,
                    {
                        id: 'function-action-2',
                        type: 'function',
                        name: 'Second Function',
                        description: '',
                        created_at: 1000,
                        updated_at: 2000,
                        config: {
                            template_id: 'test-template-id',
                            inputs: {
                                url: { value: 'https://another-url.com' },
                            },
                        },
                    },
                ],
            }

            mockApi.createHogFlowTemplate.mockResolvedValue({ ...workflow, id: 'created-id' } as any)

            const logic = workflowLogic({ id: 'test-workflow-id' })
            logic.mount()

            await expectLogic(logic, () => {
                ;(logic.actions as any).loadHogFunctionTemplatesByIdSuccess({
                    'test-template-id': mockHogFunctionTemplate,
                } as Record<string, HogFunctionTemplateType>)
            })

            await expectLogic(logic, () => {
                logic.actions.loadWorkflowSuccess(workflow)
            }).toDispatchActions(['loadWorkflowSuccess', 'resetWorkflow'])

            await expectLogic(logic, () => {
                ;(logic.actions as any).saveAsTemplate()
            }).toDispatchActions(['saveAsTemplate'])

            const callArg = mockApi.createHogFlowTemplate.mock.calls[0][0]
            const functionActions = callArg.actions?.filter((a: HogFlowAction) => a.type === 'function') || []

            expect(functionActions).toHaveLength(2)
            functionActions.forEach((action: HogFlowAction) => {
                if ('inputs' in action.config) {
                    expect(action.config.inputs).toEqual({
                        url: { value: 'https://example.com' },
                        method: { value: 'POST' },
                    })
                }
            })
        })

        it('should handle function action with no matching template', async () => {
            const baseWorkflow = createWorkflowWithFunctionAction()
            const workflow: HogFlow = {
                ...baseWorkflow,
                actions: [
                    {
                        id: 'function-action-no-template',
                        type: 'function',
                        name: 'Function Without Template',
                        description: '',
                        created_at: 1000,
                        updated_at: 2000,
                        config: {
                            template_id: 'non-existent-template-id',
                            inputs: {
                                url: { value: 'https://custom-url.com' },
                            },
                        },
                    },
                ],
            }

            mockApi.createHogFlowTemplate.mockResolvedValue({ ...workflow, id: 'created-id' } as any)

            const logic = workflowLogic({ id: 'test-workflow-id' })
            logic.mount()

            // Set hogFunctionTemplatesById without the non-existent template
            await expectLogic(logic, () => {
                ;(logic.actions as any).loadHogFunctionTemplatesByIdSuccess({
                    'test-template-id': mockHogFunctionTemplate,
                } as Record<string, HogFunctionTemplateType>)
            })

            await expectLogic(logic, () => {
                logic.actions.loadWorkflowSuccess(workflow)
            }).toDispatchActions(['loadWorkflowSuccess', 'resetWorkflow'])

            await expectLogic(logic, () => {
                ;(logic.actions as any).saveAsTemplate()
            }).toDispatchActions(['saveAsTemplate'])

            // Should still create template, but function action inputs should remain unchanged
            const callArg = mockApi.createHogFlowTemplate.mock.calls[0][0]
            const functionAction = callArg.actions?.find((a: HogFlowAction) => a.id === 'function-action-no-template')
            if (functionAction && 'inputs' in functionAction.config) {
                expect(functionAction.config.inputs).toEqual({
                    url: { value: 'https://custom-url.com' },
                })
            }
        })

        it('should handle trigger webhook-function actions', async () => {
            const triggerFunctionTemplate: HogFunctionTemplateType = {
                id: 'trigger-template-id',
                name: 'Trigger Template',
                type: 'source_webhook',
                code: '',
                code_language: 'hog',
                status: 'stable',
                free: true,
                inputs_schema: [
                    {
                        key: 'webhook_url',
                        type: 'string',
                        label: 'Webhook URL',
                        required: true,
                        default: 'https://default-webhook.com',
                    },
                ],
            }

            const baseWorkflow = createWorkflowWithFunctionAction()
            const workflow: HogFlow = {
                ...baseWorkflow,
                actions: [
                    {
                        id: 'trigger-function-action',
                        type: 'trigger',
                        name: 'Trigger Function',
                        description: '',
                        created_at: 1000,
                        updated_at: 2000,
                        config: {
                            type: 'webhook',
                            template_id: 'trigger-template-id',
                            inputs: {
                                webhook_url: { value: 'https://custom-webhook.com' },
                            },
                        },
                    },
                ],
            }

            mockApi.createHogFlowTemplate.mockResolvedValue({ ...workflow, id: 'created-id' } as any)

            const logic = workflowLogic({ id: 'test-workflow-id' })
            logic.mount()

            await expectLogic(logic, () => {
                ;(logic.actions as any).loadHogFunctionTemplatesByIdSuccess({
                    'trigger-template-id': triggerFunctionTemplate,
                })
            })

            await expectLogic(logic, () => {
                logic.actions.loadWorkflowSuccess(workflow)
            }).toDispatchActions(['loadWorkflowSuccess', 'resetWorkflow'])

            await expectLogic(logic, () => {
                ;(logic.actions as any).saveAsTemplate()
            }).toDispatchActions(['saveAsTemplate'])

            const callArg = mockApi.createHogFlowTemplate.mock.calls[0][0]
            const triggerAction = callArg.actions?.find((a: HogFlowAction) => a.id === 'trigger-function-action')
            if (triggerAction && 'inputs' in triggerAction.config) {
                expect(triggerAction.config.inputs).toEqual({
                    webhook_url: { value: 'https://default-webhook.com' },
                })
            }
        })
    })
})
