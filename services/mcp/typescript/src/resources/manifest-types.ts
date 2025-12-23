/**
 * Type definitions for the resource manifest
 * The manifest is the source of truth for all URIs and resource definitions
 */

export interface WorkflowResource {
    id: string
    name: string
    description: string
    file: string
    order: number
    uri: string
    nextStepId?: string
    nextStepUri?: string
}

export interface ExampleResource {
    id: string
    name: string
    description: string
    file: string
    uri: string
}

export interface DocResource {
    id: string
    name: string
    description: string
    uri: string
    url: string
}

export interface PromptResource {
    id: string
    name: string
    title: string
    description: string
    messages: Array<{
        role: string
        content: {
            type: string
            text: string
        }
    }>
}

export interface ResourceTemplate {
    name: string
    uriPattern: string
    description: string
    parameterName: string
    items: Array<{
        id: string
        file?: string
        url?: string
    }>
}

export interface ResourceManifest {
    version: string
    resources: {
        workflows: WorkflowResource[]
        docs: DocResource[]
        prompts: PromptResource[]
    }
    templates?: ResourceTemplate[]
}
