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

/**
 * Context-mill manifest types
 *
 * Only the fields the MCP server needs to register resources are typed here.
 * Context-mill may include arbitrary additional fields — the MCP server
 * ignores them and never needs updating when context-mill's schema evolves.
 */
export interface ContextMillResource {
    /** Used for logging and archive validation */
    id: string
    /** MCP resource registration name */
    name: string
    /** MCP resource URI */
    uri: string
    /** Filename in the archive (for validation). Absent for inline resources. */
    file?: string
    /** Complete MCP resource representation, served directly to clients */
    resource: {
        mimeType: string
        description: string
        text: string
        [key: string]: unknown
    }
    /** Any additional fields from context-mill are allowed */
    [key: string]: unknown
}

export interface ContextMillManifest {
    version: string
    resources: ContextMillResource[]
    [key: string]: unknown
}
