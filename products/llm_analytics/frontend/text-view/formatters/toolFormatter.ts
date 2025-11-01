/**
 * Format available tools section for text view
 */

interface Tool {
    type?: string
    function?: {
        name: string
        description?: string
        parameters?: Record<string, any>
    }
    name?: string
    description?: string
    input_schema?: Record<string, any> // Anthropic format (snake_case)
    inputSchema?: Record<string, any> // OpenAI format (camelCase)
    functionDeclarations?: Tool[] // Google/Gemini format
    parameters?: Record<string, any> // Google/Gemini format (unwrapped)
}

/**
 * Format available tools section
 */
export function formatTools(aiTools: any): string[] {
    const lines: string[] = []

    if (!aiTools || !Array.isArray(aiTools) || aiTools.length === 0) {
        return lines
    }

    lines.push('')
    lines.push(`AVAILABLE TOOLS: ${aiTools.length}`)

    for (const tool of aiTools as Tool[]) {
        // Handle Google/Gemini format: {functionDeclarations: [{name, description, parameters}]}
        let toolsToProcess: Tool[] = []
        if ('functionDeclarations' in tool && Array.isArray(tool.functionDeclarations)) {
            toolsToProcess = tool.functionDeclarations as Tool[]
        } else {
            toolsToProcess = [tool]
        }

        for (const t of toolsToProcess) {
            let name: string
            let desc: string
            let schema: Record<string, any> | undefined

            // Handle different tool formats
            if (t.function) {
                // OpenAI format: {type: 'function', function: {name, description, parameters}}
                name = t.function.name
                desc = t.function.description || 'N/A'
                schema = t.function.parameters
            } else if (t.name) {
                // Multiple formats:
                // - Anthropic: {name, description, input_schema} (snake_case)
                // - OpenAI: {name, description, inputSchema} (camelCase)
                // - Google/Gemini unwrapped: {name, description, parameters}
                name = t.name
                desc = t.description || 'N/A'
                schema = (t as any).input_schema || (t as any).inputSchema || (t as any).parameters
            } else {
                // Unknown format
                name = (t as any).type || 'UNKNOWN'
                desc = JSON.stringify(t).slice(0, 100)
                schema = undefined
            }

            // Build function signature from schema
            let signature = `${name}(`
            if (schema && schema.properties) {
                const properties = schema.properties
                const required = schema.required || []
                const params: string[] = []

                for (const [paramName, paramInfo] of Object.entries(properties)) {
                    const paramType = (paramInfo as any).type || 'any'
                    if (required.includes(paramName)) {
                        params.push(`${paramName}: ${paramType}`)
                    } else {
                        params.push(`${paramName}?: ${paramType}`)
                    }
                }
                signature += params.join(', ')
            }
            signature += ')'

            // Show signature
            lines.push('')
            lines.push(`  ${signature}`)

            // Show only first line of description (up to first newline or sentence)
            if (desc && desc !== 'N/A') {
                // Split by newline first, then by sentence
                const firstLine = desc.split('\n')[0]
                const firstSentence = firstLine.split('. ')[0]
                const finalSentence = firstSentence.endsWith('.') ? firstSentence : `${firstSentence}.`
                lines.push(`    ${finalSentence}`)
            }
        }
    }

    return lines
}
