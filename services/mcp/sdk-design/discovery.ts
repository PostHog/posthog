export interface ToolTypeReference {
    name: string
    /** npm subpath from which an agent can import this type. */
    importPath: string
    /** Path relative to the installed package root, independent of the checkout that generated it. */
    source: string
    declaration: string
}

export interface DocumentationSource {
    kind: 'openapi' | 'query_schema' | 'mcp_yaml' | 'description_file' | 'adapter'
    file: string
    pointer?: string
}

export interface DocumentationLayer {
    role: 'original' | 'override' | 'generated'
    text: string
    source: DocumentationSource
}

export interface TypeDocumentation {
    typeName: string
    /** Omit for documentation on the interface itself. */
    field?: string
    effectiveDescription: string
    layers: DocumentationLayer[]
}

export interface ToolAnnotations {
    readOnly: boolean
    destructive: boolean
    idempotent: boolean
}

export interface RelatedTool {
    toolName: string
    method?: string
    /** Explains why an MCP tool mentioned in the description has no exported SDK method. */
    unavailableReason?: string
}

export interface ToolSearchResult {
    method: string
    toolName: string
    title: string
    selectionHint?: string
    /** Package-relative path to the full description, documentation provenance, and interface references. */
    descriptionFile: string
}

export interface ToolSearchOptions {
    limit?: number
}

export interface ToolDescription {
    method: string
    toolName: string
    operationId?: string
    title: string
    category: string
    description: string
    selectionHint?: string
    requiredScopes: string[]
    annotations: ToolAnnotations
    availability: string[]
    methodSource: string
    input: ToolTypeReference
    output: ToolTypeReference
    /** Includes nested interfaces so discovery does not stop at a top-level output envelope. */
    referencedTypes: ToolTypeReference[]
    methodDocumentation: DocumentationLayer[]
    typeDocumentation: TypeDocumentation[]
    relatedTools: RelatedTool[]
}

export interface ToolCatalog {
    schemaVersion: number
    packageVersion: string
    sourceRevision: string
    schemaHash: string
    tools: ToolSearchResult[]
}

/** Static package data; these declarations do not implement discovery in the design sketch. */
export declare const catalog: ToolCatalog

/** Searches local descriptions, selection hints, method names, and MCP tool names without credentials or HTTP calls. */
export declare function searchTools(query: string, options?: ToolSearchOptions): ToolSearchResult[]

/** Accepts a method path or MCP tool name and returns its full generated documentation. */
export declare function describeTool(methodOrToolName: string): ToolDescription | undefined
