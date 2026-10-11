export interface OperationInfo {
    readonly domain: string
    readonly method: string
    readonly toolName: string
    readonly title: string
    readonly purpose: string
    readonly input: string
    readonly output: string
    readonly requiredScopes: readonly string[]
    readonly readOnly: boolean
    readonly destructive: boolean
    readonly idempotent: boolean
    readonly availability: readonly string[]
}

export interface ToolDomain {
    readonly domain: string
    readonly methods: number
    readonly importPath: string
}

export declare const operations: readonly OperationInfo[]
export declare const domains: readonly ToolDomain[]
