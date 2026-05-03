/**
 * ClientGenerator: takes an OpenAPI spec + tool-definitions metadata + known schema names
 * + (optionally) a YAML index of enabled tools/wrappers, and emits client.ts, sdk.d.ts,
 * and search-docs.
 *
 * Extracted as its own module so tests can drive it against fixture specs without spawning
 * the script.
 *
 * When `yamlIndex` is provided, only operations whose `operationId` appears in
 * `yamlIndex.enabled` are emitted, and per-tool YAML descriptions/titles override the
 * OpenAPI summary/description. Special methods (mcp_tools/* + query wrappers) are always
 * emitted alongside OpenAPI ops.
 */
import type { EnabledWrapper, YamlIndex } from './load-yaml'
import type { SpecialMethod } from './special-tools'

export interface OpenApiRef {
    $ref: string
}

export interface OpenApiSchema {
    type?: string
    format?: string
    description?: string
    nullable?: boolean
    readOnly?: boolean
    items?: OpenApiSchema | OpenApiRef
    properties?: Record<string, OpenApiSchema | OpenApiRef>
    required?: string[]
    $ref?: string
    enum?: Array<string | number>
    default?: unknown
}

export interface OpenApiParameter {
    in: 'path' | 'query' | 'header' | 'cookie'
    name: string
    required?: boolean
    description?: string
    schema: OpenApiSchema
}

export interface OpenApiOperation {
    operationId?: string
    summary?: string
    description?: string
    parameters?: OpenApiParameter[]
    requestBody?: {
        required?: boolean
        content?: {
            'application/json'?: { schema: OpenApiSchema | OpenApiRef }
        }
    }
    responses?: Record<
        string,
        {
            description?: string
            content?: {
                'application/json'?: { schema: OpenApiSchema | OpenApiRef }
            }
        }
    >
}

export interface OpenApiSpec {
    paths: Record<string, Record<string, OpenApiOperation>>
    components?: { schemas?: Record<string, OpenApiSchema> }
}

export interface ToolDefinitionMeta {
    description?: string
    summary?: string
    title?: string
    category?: string
}

export interface ResolvedOperation {
    operationId: string
    methodName: string
    httpMethod: string
    urlPath: string
    summary: string
    description: string
    pathParams: OpenApiParameter[]
    queryParams: OpenApiParameter[]
    bodyTypeRef?: string
    bodyInline?: OpenApiSchema
    responseTypeRef?: string
    responseIsArray: boolean
}

export interface SearchDoc {
    id: string
    kind: 'operation' | 'type'
    name: string
    description: string
    summary: string
    snippet: string
}

/**
 * Path params that the Context can resolve from /api/users/@me/ when the agent
 * doesn't pass them explicitly. environment_id aliases to project_id at the API layer.
 */
const AUTO_RESOLVED_PATH_PARAMS: Record<string, string> = {
    project_id: 'getProjectId',
    organization_id: 'getOrganizationId',
    environment_id: 'getEnvironmentId',
}

export interface ClientGeneratorOptions {
    /** When set, only operations whose operationId is in `yamlIndex.enabled` are emitted. */
    yamlIndex?: YamlIndex
    /** Hand-listed methods backed by the mcp_tools/* endpoint. */
    specialMethods?: SpecialMethod[]
}

export class ClientGenerator {
    private readonly yamlIndex: YamlIndex | undefined
    private readonly specialMethods: SpecialMethod[]

    constructor(
        private spec: OpenApiSpec,
        private definitions: Record<string, ToolDefinitionMeta>,
        private knownSchemas: Set<string>,
        options: ClientGeneratorOptions = {}
    ) {
        this.yamlIndex = options.yamlIndex
        this.specialMethods = options.specialMethods ?? []
    }

    private isAutoResolved(paramName: string): boolean {
        return paramName in AUTO_RESOLVED_PATH_PARAMS
    }

    private allPathParamsAutoResolved(op: ResolvedOperation): boolean {
        return op.pathParams.length > 0 && op.pathParams.every((p) => this.isAutoResolved(p.name))
    }

    private inputIsFullyOptional(op: ResolvedOperation): boolean {
        const pathOptional = op.pathParams.length === 0 || this.allPathParamsAutoResolved(op)
        const queryAllOptional = op.queryParams.every((p) => !p.required)
        const noBody = !op.bodyTypeRef && !op.bodyInline
        return pathOptional && queryAllOptional && noBody
    }

    collectOperations(): ResolvedOperation[] {
        const ops: ResolvedOperation[] = []
        const seenMethodNames = new Set<string>()

        for (const [urlPath, methods] of Object.entries(this.spec.paths)) {
            for (const [httpMethod, op] of Object.entries(methods)) {
                if (!op?.operationId) {
                    continue
                }
                if (this.yamlIndex && !this.yamlIndex.enabled.has(op.operationId)) {
                    continue
                }
                const methodName = this.deriveMethodName(op.operationId, urlPath)
                if (seenMethodNames.has(methodName)) {
                    continue
                }
                seenMethodNames.add(methodName)

                const params = op.parameters ?? []
                const pathParams = params.filter((p) => p.in === 'path')
                const queryParams = params.filter((p) => p.in === 'query' && p.name !== 'format')

                const yamlOp = this.yamlIndex?.enabled.get(op.operationId)
                const meta = this.lookupDefinitionMeta(op.operationId)
                const summary = yamlOp?.title ?? yamlOp?.summary ?? meta?.summary ?? op.summary ?? ''
                const description = yamlOp?.description ?? meta?.description ?? op.description ?? ''

                const bodyResolved = this.resolveBodyType(op)
                const responseResolved = this.resolveResponseType(op)

                ops.push({
                    operationId: op.operationId,
                    methodName,
                    httpMethod: httpMethod.toUpperCase(),
                    urlPath,
                    summary,
                    description,
                    pathParams,
                    queryParams,
                    bodyTypeRef: bodyResolved.typeRef,
                    bodyInline: bodyResolved.inline,
                    responseTypeRef: responseResolved.typeRef,
                    responseIsArray: responseResolved.isArray,
                })
            }
        }
        return ops.sort((a, b) => a.methodName.localeCompare(b.methodName))
    }

    renderClientTs(ops: ResolvedOperation[]): string {
        const lines: string[] = []
        lines.push('// AUTO-GENERATED — do not edit. Regenerate with `pnpm --filter @posthog/mcp-exec generate`.')
        lines.push("import type { Schemas } from './sdk'")
        lines.push("import type { HttpClient } from '../lib/http-client'")
        lines.push("import type { Context } from '../lib/context'")
        lines.push('')

        const inputInterfaces: string[] = []
        const methods: string[] = []

        for (const op of ops) {
            const inputName = this.inputInterfaceName(op)
            const responseType = this.formatResponseType(op)
            const inputDef = this.renderInputInterface(inputName, op)

            if (inputDef) {
                inputInterfaces.push(inputDef)
            }
            methods.push(this.renderClientMethod(op, inputName, responseType, !!inputDef))
        }

        for (const m of this.specialMethods) {
            if (m.inputDecl) {
                inputInterfaces.push(m.inputDecl + '\n')
            }
            methods.push(this.renderSpecialMethod(m))
        }

        const wrappers = this.yamlIndex?.wrappers ?? []
        for (const w of wrappers) {
            methods.push(this.renderQueryWrapperMethod(w))
        }

        lines.push(...inputInterfaces)
        lines.push('export class Client {')
        lines.push('    constructor(private http: HttpClient, private context: Context) {}')
        lines.push('')
        lines.push(...methods)
        if (this.specialMethods.length > 0) {
            lines.push(this.renderInvokeMcpToolHelper())
        }
        if (wrappers.length > 0) {
            lines.push(this.renderRunQueryHelper())
        }
        lines.push('}')
        lines.push('')
        return lines.join('\n')
    }

    renderSdkDts(ops: ResolvedOperation[], schemasNamespaceSource: string): string {
        const lines: string[] = []
        lines.push('// AUTO-GENERATED — agent-facing SDK surface for the @posthog/mcp-exec server.')
        lines.push('// Read this file with the `read` tool. The Schemas namespace contains every API type;')
        lines.push('// the Client interface lists every operation as a method.')
        lines.push('')
        lines.push(schemasNamespaceSource.trim())
        lines.push('')

        const inputInterfaces: string[] = []
        const methodSignatures: string[] = []

        for (const op of ops) {
            const inputName = this.inputInterfaceName(op)
            const responseType = this.formatResponseType(op)
            const inputDef = this.renderInputInterface(inputName, op)
            if (inputDef) {
                inputInterfaces.push(inputDef)
            }
            const fullyOptional = this.inputIsFullyOptional(op)
            const inputArg = inputDef ? (fullyOptional ? `input?: ${inputName}` : `input: ${inputName}`) : ''
            const opComment = this.renderOperationDocComment(op)
            methodSignatures.push(opComment)
            methodSignatures.push(`    ${op.methodName}(${inputArg}): Promise<${responseType}>`)
            methodSignatures.push('')
        }

        for (const m of this.specialMethods) {
            if (m.inputDecl) {
                inputInterfaces.push(m.inputDecl + '\n')
            }
            methodSignatures.push(this.renderSpecialMethodDocComment(m))
            const inputArg = m.inputName ? `input: ${m.inputName}` : ''
            methodSignatures.push(`    ${m.methodName}(${inputArg}): Promise<${m.responseType}>`)
            methodSignatures.push('')
        }

        for (const w of this.yamlIndex?.wrappers ?? []) {
            methodSignatures.push(this.renderQueryWrapperDocComment(w))
            methodSignatures.push(
                `    ${this.queryWrapperMethodName(w)}(input: { query: Record<string, unknown> }): Promise<unknown>`
            )
            methodSignatures.push('')
        }

        lines.push(...inputInterfaces)
        lines.push('export interface Client {')
        lines.push(...methodSignatures)
        lines.push('}')
        lines.push('')
        return lines.join('\n')
    }

    buildSearchDocs(ops: ResolvedOperation[], schemasNamespaceSource: string): SearchDoc[] {
        const docs: SearchDoc[] = []

        for (const op of ops) {
            docs.push({
                id: `op:${op.methodName}`,
                kind: 'operation',
                name: op.methodName,
                description: op.description,
                summary: op.summary,
                snippet: `${op.httpMethod} ${op.urlPath}${op.summary ? ` — ${op.summary}` : ''}`,
            })
        }

        for (const m of this.specialMethods) {
            docs.push({
                id: `op:${m.methodName}`,
                kind: 'operation',
                name: m.methodName,
                description: m.description,
                summary: m.summary,
                snippet: `client.${m.methodName}() — ${m.summary}`,
            })
        }

        for (const w of this.yamlIndex?.wrappers ?? []) {
            const methodName = this.queryWrapperMethodName(w)
            const summary = w.title ?? w.systemPromptHint ?? `Run a ${w.schemaRef} query`
            docs.push({
                id: `op:${methodName}`,
                kind: 'operation',
                name: methodName,
                description: w.description ?? summary,
                summary,
                snippet: `client.${methodName}({ query: <${w.schemaRef}> }) — ${summary}`,
            })
        }

        for (const typeDoc of this.extractTypeDocs(schemasNamespaceSource)) {
            docs.push(typeDoc)
        }

        return docs
    }

    private renderInputInterface(name: string, op: ResolvedOperation): string | null {
        const sections: string[] = []

        if (op.pathParams.length > 0) {
            const pathLines = op.pathParams.map((p) => {
                const ts = this.openApiToTs(p.schema)
                const isAuto = this.isAutoResolved(p.name)
                const optional = isAuto || p.required === false ? '?' : ''
                const autoNote = isAuto ? ` Auto-resolved from /api/users/@me/ if omitted.` : ''
                const fullDesc = ((p.description ?? '') + autoNote).trim()
                const desc = fullDesc ? `        /** ${this.escapeComment(fullDesc)} */\n` : ''
                return `${desc}        ${this.safeKey(p.name)}${optional}: ${ts}`
            })
            const pathOptional = this.allPathParamsAutoResolved(op) ? '?' : ''
            sections.push(`    path${pathOptional}: {\n${pathLines.join('\n')}\n    }`)
        }

        if (op.queryParams.length > 0) {
            const queryLines = op.queryParams.map((p) => {
                const ts = this.openApiToTs(p.schema)
                const optional = p.required ? '' : '?'
                const desc = p.description ? `        /** ${this.escapeComment(p.description)} */\n` : ''
                return `${desc}        ${this.safeKey(p.name)}${optional}: ${ts}`
            })
            sections.push(`    query?: {\n${queryLines.join('\n')}\n    }`)
        }

        if (op.bodyTypeRef) {
            sections.push(`    body: ${op.bodyTypeRef}`)
        } else if (op.bodyInline) {
            const ts = this.openApiToTs(op.bodyInline)
            sections.push(`    body: ${ts}`)
        }

        if (sections.length === 0) {
            return null
        }
        return `export interface ${name} {\n${sections.join('\n')}\n}\n`
    }

    private renderClientMethod(
        op: ResolvedOperation,
        inputName: string,
        responseType: string,
        hasInput: boolean
    ): string {
        const fullyOptional = this.inputIsFullyOptional(op)
        const inputArg = hasInput ? (fullyOptional ? `input: ${inputName} = {}` : `input: ${inputName}`) : ''
        const inputAccessor = hasInput ? 'input' : 'undefined'

        const resolverLines: string[] = []
        for (const p of op.pathParams) {
            const key = this.safeKey(p.name)
            if (this.isAutoResolved(p.name)) {
                const getter = AUTO_RESOLVED_PATH_PARAMS[p.name]!
                resolverLines.push(
                    `        const ${p.name} = ${inputAccessor}?.path?.${key} ?? (await this.context.${getter}())`
                )
            } else {
                resolverLines.push(`        const ${p.name} = ${inputAccessor}!.path!.${key}`)
            }
        }

        const pathExpr = this.renderPathExpr(op)
        const queryExpr = op.queryParams.length > 0 ? `${inputAccessor}?.query` : 'undefined'
        const bodyExpr = op.bodyTypeRef || op.bodyInline ? `${inputAccessor}?.body as unknown` : 'undefined'

        const lines: string[] = []
        lines.push(`    async ${op.methodName}(${inputArg}): Promise<${responseType}> {`)
        lines.push(...resolverLines)
        lines.push(`        return this.http.request<${responseType}>({`)
        lines.push(`            method: '${op.httpMethod}',`)
        lines.push(`            path: ${pathExpr},`)
        lines.push(`            query: ${queryExpr},`)
        lines.push(`            body: ${bodyExpr},`)
        lines.push(`        })`)
        lines.push(`    }`)
        lines.push('')
        return lines.join('\n')
    }

    private renderSpecialMethod(m: SpecialMethod): string {
        const inputArg = m.inputName ? `input: ${m.inputName}` : ''
        const argsExpr = m.inputName ? 'input as unknown as Record<string, unknown>' : '{}'
        const lines: string[] = []
        lines.push(this.renderSpecialMethodDocComment(m))
        lines.push(`    async ${m.methodName}(${inputArg}): Promise<${m.responseType}> {`)
        lines.push(`        return this.invokeMcpTool<${m.responseType}>('${m.backendName}', ${argsExpr})`)
        lines.push(`    }`)
        lines.push('')
        return lines.join('\n')
    }

    private renderQueryWrapperMethod(w: EnabledWrapper): string {
        const methodName = this.queryWrapperMethodName(w)
        const lines: string[] = []
        lines.push(this.renderQueryWrapperDocComment(w))
        lines.push(`    async ${methodName}(input: { query: Record<string, unknown> }): Promise<unknown> {`)
        lines.push(`        return this.runQuery(input.query)`)
        lines.push(`    }`)
        lines.push('')
        return lines.join('\n')
    }

    private renderInvokeMcpToolHelper(): string {
        // Mirrors services/mcp/src/tools/posthogAiTools/invokeTool.ts. The endpoint always
        // returns 200 with `{ success, content }`; we throw on success: false so the
        // SnippetRunner classifies it as a runtime error rather than returning a silent failure.
        const lines: string[] = []
        lines.push('')
        lines.push('    private async invokeMcpTool<T>(name: string, args: Record<string, unknown>): Promise<T> {')
        lines.push('        const project_id = await this.context.getProjectId()')
        lines.push('        const result = await this.http.request<{ success: boolean; content: unknown }>({')
        lines.push("            method: 'POST',")
        lines.push(
            '            path: `/api/environments/${encodeURIComponent(project_id)}/mcp_tools/${encodeURIComponent(name)}/`,'
        )
        lines.push('            body: { args },')
        lines.push('        })')
        lines.push('        if (!result.success) {')
        lines.push(
            "            throw new Error(typeof result.content === 'string' ? result.content : JSON.stringify(result.content))"
        )
        lines.push('        }')
        lines.push('        return result.content as T')
        lines.push('    }')
        return lines.join('\n')
    }

    private renderRunQueryHelper(): string {
        const lines: string[] = []
        lines.push('')
        lines.push('    private async runQuery(query: Record<string, unknown>): Promise<unknown> {')
        lines.push('        const project_id = await this.context.getProjectId()')
        lines.push('        return this.http.request<unknown>({')
        lines.push("            method: 'POST',")
        lines.push('            path: `/api/environments/${encodeURIComponent(project_id)}/query/`,')
        lines.push('            body: { query },')
        lines.push('        })')
        lines.push('    }')
        return lines.join('\n')
    }

    private renderSpecialMethodDocComment(m: SpecialMethod): string {
        const lines: string[] = []
        lines.push('    /**')
        lines.push(`     * ${m.summary}`)
        if (m.description) {
            lines.push('     *')
            for (const descLine of m.description.split('\n')) {
                lines.push(`     * ${descLine}`)
            }
        }
        lines.push('     */')
        return lines.join('\n')
    }

    private renderQueryWrapperDocComment(w: EnabledWrapper): string {
        const lines: string[] = []
        lines.push('    /**')
        lines.push(`     * ${w.title ?? `Run a ${w.schemaRef} query`}`)
        lines.push('     *')
        lines.push(`     * POST /api/environments/{project_id}/query/ with body { query: <${w.schemaRef}> }.`)
        if (w.systemPromptHint) {
            lines.push('     *')
            lines.push(`     * When to use: ${w.systemPromptHint}`)
        }
        if (w.description) {
            lines.push('     *')
            for (const descLine of w.description.split('\n')) {
                lines.push(`     * ${descLine}`)
            }
        }
        lines.push('     */')
        return lines.join('\n')
    }

    private queryWrapperMethodName(w: EnabledWrapper): string {
        return this.toCamelCase(w.toolName)
    }

    private renderPathExpr(op: ResolvedOperation): string {
        if (op.pathParams.length === 0) {
            return `\`${op.urlPath}\``
        }
        let result = op.urlPath
        for (const p of op.pathParams) {
            const placeholder = `{${p.name}}`
            const replacement = `\${encodeURIComponent(String(${p.name}))}`
            result = result.split(placeholder).join(replacement)
        }
        return `\`${result}\``
    }

    private renderOperationDocComment(op: ResolvedOperation): string {
        const lines: string[] = []
        lines.push('    /**')
        lines.push(`     * ${op.httpMethod} ${op.urlPath}`)
        if (op.summary) {
            lines.push(`     *`)
            lines.push(`     * ${op.summary}`)
        }
        if (op.description && op.description !== op.summary) {
            lines.push(`     *`)
            for (const descLine of op.description.split('\n')) {
                lines.push(`     * ${descLine}`)
            }
        }
        lines.push('     */')
        return lines.join('\n')
    }

    private resolveBodyType(op: OpenApiOperation): { typeRef?: string; inline?: OpenApiSchema } {
        const schema = op.requestBody?.content?.['application/json']?.schema
        if (!schema) {
            return {}
        }
        if ('$ref' in schema && schema.$ref) {
            const name = schema.$ref.replace('#/components/schemas/', '')
            if (this.knownSchemas.has(name)) {
                return { typeRef: `Schemas.${name}` }
            }
        }
        return { inline: schema as OpenApiSchema }
    }

    private resolveResponseType(op: OpenApiOperation): { typeRef?: string; isArray: boolean } {
        for (const status of ['200', '201', '202', '204']) {
            const content = op.responses?.[status]?.content?.['application/json']
            if (!content?.schema) {
                continue
            }
            const schema = content.schema as OpenApiSchema & OpenApiRef
            if (schema.$ref) {
                const name = schema.$ref.replace('#/components/schemas/', '')
                if (this.knownSchemas.has(name)) {
                    return { typeRef: `Schemas.${name}`, isArray: false }
                }
            }
            if (schema.type === 'array' && schema.items && '$ref' in schema.items && schema.items.$ref) {
                const name = schema.items.$ref.replace('#/components/schemas/', '')
                if (this.knownSchemas.has(name)) {
                    return { typeRef: `Schemas.${name}`, isArray: true }
                }
            }
        }
        return { isArray: false }
    }

    private formatResponseType(op: ResolvedOperation): string {
        if (!op.responseTypeRef) {
            return 'unknown'
        }
        return op.responseIsArray ? `${op.responseTypeRef}[]` : op.responseTypeRef
    }

    private openApiToTs(schema: OpenApiSchema | OpenApiRef): string {
        if ('$ref' in schema && schema.$ref) {
            const name = schema.$ref.replace('#/components/schemas/', '')
            if (this.knownSchemas.has(name)) {
                return `Schemas.${name}`
            }
            return 'unknown'
        }
        const s = schema as OpenApiSchema
        if (s.enum && s.enum.length > 0) {
            return s.enum.map((v) => (typeof v === 'string' ? `'${v.replace(/'/g, "\\'")}'` : String(v))).join(' | ')
        }
        if (s.type === 'array' && s.items) {
            return `${this.openApiToTs(s.items)}[]`
        }
        if (s.type === 'object') {
            return 'Record<string, unknown>'
        }
        if (s.type === 'integer' || s.type === 'number') {
            return 'number'
        }
        if (s.type === 'boolean') {
            return 'boolean'
        }
        if (s.type === 'string') {
            return 'string'
        }
        return 'unknown'
    }

    private extractTypeDocs(schemasNamespaceSource: string): SearchDoc[] {
        const docs: SearchDoc[] = []
        const re = /(?:\/\*\*\s*([\s\S]*?)\*\/\s*)?export\s+(?:type|interface|const)\s+([A-Z][A-Za-z0-9_]*)/g
        let match: RegExpExecArray | null
        while ((match = re.exec(schemasNamespaceSource)) !== null) {
            const jsdoc = (match[1] ?? '').replace(/^\s*\*\s?/gm, '').trim()
            const name = match[2]!
            const firstLine = jsdoc.split('\n')[0]?.trim() ?? ''
            docs.push({
                id: `type:${name}`,
                kind: 'type',
                name,
                description: jsdoc,
                summary: firstLine,
                snippet: firstLine ? `Schemas.${name} — ${firstLine}` : `Schemas.${name}`,
            })
        }
        return docs
    }

    private lookupDefinitionMeta(operationId: string): ToolDefinitionMeta | undefined {
        const kebabFromSnake = operationId.replace(/_/g, '-')
        if (this.definitions[kebabFromSnake]) {
            return this.definitions[kebabFromSnake]
        }
        return undefined
    }

    /**
     * Derive the Input interface name from the method name (PascalCase methodName + "Input").
     * Keeps the agent-facing name aligned with the method itself rather than the raw operationId.
     */
    private inputInterfaceName(op: ResolvedOperation): string {
        return op.methodName.charAt(0).toUpperCase() + op.methodName.slice(1) + 'Input'
    }

    /**
     * PostHog's OpenAPI spec sometimes uses generic operationIds like `list_2` or `create_3`
     * that produce useless method names. When the operationId is generic, derive the name
     * from the URL path instead — e.g. `list_2` at `/api/organizations/{}/projects/` becomes
     * `organizationsProjectsList`.
     */
    private deriveMethodName(operationId: string, urlPath: string): string {
        const genericVerbs = /^(list|create|retrieve|update|partial_update|destroy)(_\d+)?$/
        const match = operationId.match(genericVerbs)
        if (!match) {
            return this.toCamelCase(operationId)
        }
        const verb = match[1]!
        const segments = urlPath
            .replace(/^\/api\//, '')
            .split('/')
            .filter((s) => s.length > 0 && !s.startsWith('{'))
        if (segments.length === 0) {
            return this.toCamelCase(operationId)
        }
        return this.toCamelCase([...segments, verb].join('_'))
    }

    private toCamelCase(snake: string): string {
        const parts = snake.split(/[_.-]/).filter(Boolean)
        if (parts.length === 0) {
            return snake
        }
        const head = parts[0]!
        const tail = parts.slice(1).map((p) => p.charAt(0).toUpperCase() + p.slice(1))
        return head + tail.join('')
    }

    private toPascalCase(snake: string): string {
        return snake
            .split(/[_.-]/)
            .filter(Boolean)
            .map((p) => p.charAt(0).toUpperCase() + p.slice(1))
            .join('')
    }

    private safeKey(name: string): string {
        if (/^[A-Za-z_$][A-Za-z0-9_$]*$/.test(name)) {
            return name
        }
        return `'${name.replace(/'/g, "\\'")}'`
    }

    private escapeComment(text: string): string {
        return text.replace(/\*\//g, '*\\/').replace(/\n/g, ' ').slice(0, 200)
    }
}
