import { actions, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { tryJsonParse } from 'lib/utils'

import { getCurrentTeamId } from 'lib/utils/getAppContext'

import { type HogFlow } from '../hogflows/types'

import { HogflowTestResult } from '../hogflows/steps/types'
import { workflowLogic } from '../workflowLogic'
import { WorkflowSceneLogicProps } from '../workflowSceneLogic'
import type { testWorkflowLogicType } from './testWorkflowLogicType'

export interface TestWorkflowForm {
    globals: string
    variables?: string
    mock_async_functions: boolean
}

export const testWorkflowLogic = kea<testWorkflowLogicType>([
    props({} as WorkflowSceneLogicProps),
    key(({ id }: WorkflowSceneLogicProps) => id ?? 'new'),
    path((id) => ['products', 'workflows', 'testing', 'testWorkflowLogic', id]),
    
    actions({
        setTestModalOpen: (open: boolean) => ({ open }),
        setTestResult: (result: HogflowTestResult | null) => ({ result }),
        clearTestResult: true,
        loadExampleEvent: true,
    }),
    
    reducers({
        testModalOpen: [
            false,
            {
                setTestModalOpen: (_, { open }) => open,
                setTestResult: () => false,
            },
        ],
        testResult: [
            null as HogflowTestResult | null,
            {
                setTestResult: (_, { result }) => result,
                clearTestResult: () => null,
            },
        ],
    }),
    
    loaders(({ props, values }) => ({
        exampleEvent: [
            null as any,
            {
                loadExampleEvent: async () => {
                    try {
                        // Get the workflow configuration
                        const logic = workflowLogic(props)
                        const workflow = logic.values.workflow
                        
                        if (!workflow?.trigger?.filters?.events) {
                            return null
                        }
                        
                        // For now, just return a default example event
                        // In the future, we could query for a real matching event
                        return {
                            event: {
                                event: workflow.trigger.filters.events[0]?.id || '$pageview',
                                distinct_id: 'test-user-123',
                                timestamp: new Date().toISOString(),
                                properties: {
                                    $browser: 'Chrome',
                                    $current_url: 'https://example.com/test',
                                    $device_type: 'Desktop',
                                },
                                elements_chain: '',
                                uuid: '01234567-89ab-cdef-0123-456789abcdef',
                                url: 'https://example.com/test',
                            },
                            person: {
                                id: 'test-person-123',
                                name: 'Test User',
                                properties: {
                                    email: 'test@example.com',
                                    name: 'Test User',
                                },
                                url: 'https://app.posthog.com/project/1/person/test-person-123',
                            },
                            groups: {},
                            project: {
                                id: 1,
                                name: 'Test Project',
                                url: 'https://app.posthog.com/project/1',
                            },
                        }
                    } catch (e) {
                        console.error('Error loading example event:', e)
                        return null
                    }
                },
            },
        ],
    })),
    
    forms(({ props, values, actions }) => ({
        testWorkflow: {
            defaults: {
                globals: '',
                variables: '',
                mock_async_functions: true,
            } as TestWorkflowForm,
            alwaysShowErrors: true,
            errors: ({ globals, variables }) => {
                const errors: Record<string, string | undefined> = {}
                
                if (!globals) {
                    errors.globals = 'Event data is required'
                } else {
                    const parsed = tryJsonParse(globals)
                    if (!parsed) {
                        errors.globals = 'Invalid JSON'
                    }
                }
                
                if (variables) {
                    const parsed = tryJsonParse(variables)
                    if (!parsed) {
                        errors.variables = 'Invalid JSON'
                    }
                }
                
                return errors
            },
            submit: async (data) => {
                try {
                    const logic = workflowLogic(props)
                    const workflow = logic.values.workflow as HogFlow
                    
                    const globals = tryJsonParse(data.globals)
                    const variables = data.variables ? tryJsonParse(data.variables) : undefined
                    
                    // Call the full invocation endpoint
                    const fullResult = await api.hogFlows.createFullTestInvocation(props.id ?? 'new', {
                        globals,
                        variables,
                        mock_async_functions: data.mock_async_functions,
                        configuration: workflow,
                    })
                    
                    actions.setTestResult(fullResult)
                    lemonToast.success('Workflow test completed')
                } catch (e: any) {
                    console.error('Test workflow error:', e)
                    lemonToast.error(`Test failed: ${e.message || 'Unknown error'}`)
                }
            },
        },
    })),
    
    listeners(({ actions, values }) => ({
        setTestModalOpen: ({ open }) => {
            if (open && !values.exampleEvent && !values.exampleEventLoading) {
                actions.loadExampleEvent()
            }
        },
        
        loadExampleEventSuccess: ({ exampleEvent }) => {
            if (exampleEvent) {
                actions.setTestWorkflowValue('globals', JSON.stringify(exampleEvent, null, 2))
            }
        },
    })),
    
    selectors(() => ({
        teamId: [
            () => [],
            () => getCurrentTeamId(),
        ],
    })),
])