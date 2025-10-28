/**
 * Format input and output messages for text view
 */
import { isObject } from 'lib/utils'

interface ToolCall {
    function?: {
        name: string
        arguments: string | Record<string, any>
    }
    name?: string
    args?: string | Record<string, any>
}

interface Message {
    role?: string
    type?: string
    content?: string | any[]
    tool_calls?: ToolCall[]
}

/**
 * Truncate content with middle ellipsis for long text
 * Embeds full content in a special marker format for click-to-expand functionality
 */
function truncateContent(content: string, maxLength = 1000): { lines: string[]; truncated: boolean } {
    if (content.length <= maxLength) {
        return { lines: [content], truncated: false }
    }

    const half = Math.floor(maxLength / 2)
    const firstPart = content.slice(0, half)
    const lastPart = content.slice(-half)
    const truncatedChars = content.length - maxLength
    const middlePart = content.slice(half, -half)

    // Encode the middle part in a special marker format that we'll parse in the display component
    // Format: <<<TRUNCATED|base64content|charCount>>>
    const encodedMiddle = btoa(encodeURIComponent(middlePart))
    const marker = `<<<TRUNCATED|${encodedMiddle}|${truncatedChars}>>>`

    return {
        lines: [firstPart, '', marker, '', lastPart],
        truncated: true,
    }
}

/**
 * Format tool calls for display
 */
function formatToolCalls(toolCalls: ToolCall[]): string[] {
    const lines: string[] = []
    lines.push(`Tool calls: ${toolCalls.length}`)

    for (const tc of toolCalls) {
        // Handle both OpenAI format (function: {name, arguments})
        // and LangChain format (name, args)
        let name: string
        let args: string | Record<string, any>

        if (tc.function) {
            name = tc.function.name
            args = tc.function.arguments
        } else {
            name = tc.name || 'unknown'
            args = tc.args || ''
        }

        // Parse args into object if needed
        let parsedArgs: Record<string, any> | null = null
        if (typeof args === 'object') {
            parsedArgs = args
        } else if (typeof args === 'string' && args) {
            try {
                parsedArgs = JSON.parse(args)
            } catch {
                // If parsing fails, will show raw string
            }
        }

        // Format as function call
        if (parsedArgs && typeof parsedArgs === 'object') {
            const argEntries = Object.entries(parsedArgs)
            if (argEntries.length > 1) {
                // Multiline for multiple args
                lines.push(`  - ${name}(`)
                for (const [k, v] of argEntries) {
                    lines.push(`      ${k}=${JSON.stringify(v)},`)
                }
                lines.push('    )')
            } else if (argEntries.length === 1) {
                // Single line for one arg
                const [k, v] = argEntries[0]
                lines.push(`  - ${name}(${k}=${JSON.stringify(v)})`)
            } else {
                // No args
                lines.push(`  - ${name}()`)
            }
        } else {
            // Fallback for unparseable args
            lines.push(`  - ${name}(${args || ''})`)
        }
    }

    return lines
}

/**
 * Extract text content from various message content formats
 */
function extractTextContent(content: any): string {
    if (typeof content === 'string') {
        return content
    }

    if (Array.isArray(content)) {
        const textParts: string[] = []
        for (const block of content) {
            if (isObject(block)) {
                if ('text' in block) {
                    textParts.push(block.text)
                } else if ('type' in block && block.type === 'tool_use') {
                    textParts.push(`[Tool use: ${block.name || 'unknown'}]`)
                }
            } else {
                textParts.push(String(block))
            }
        }
        return textParts.join('\n')
    }

    return String(content)
}

/**
 * Format input messages section
 */
export function formatInputMessages(aiInput: any): string[] {
    const lines: string[] = []

    if (!aiInput || (Array.isArray(aiInput) && aiInput.length === 0)) {
        return lines
    }

    lines.push('')
    lines.push('INPUT:')

    // Handle simple string input
    if (typeof aiInput === 'string') {
        lines.push('')
        lines.push('[User input]')
        const { lines: contentLines } = truncateContent(aiInput)
        lines.push(...contentLines)
        return lines
    }

    // Handle array of message objects
    if (Array.isArray(aiInput)) {
        for (let i = 0; i < aiInput.length; i++) {
            const msg = aiInput[i] as Message
            const role = msg.role || msg.type || 'unknown'
            const content = msg.content || ''
            const toolCalls = msg.tool_calls || []

            lines.push('')
            lines.push(`[${i + 1}] ${role.toUpperCase()}`)
            lines.push('')

            if (content) {
                const textContent = extractTextContent(content)
                if (textContent) {
                    const { lines: contentLines } = truncateContent(textContent)
                    lines.push(...contentLines)
                }
            }

            if (toolCalls.length > 0) {
                lines.push('')
                lines.push(...formatToolCalls(toolCalls))
            }

            // Add separator between messages (but not after the last one)
            if (i < aiInput.length - 1) {
                lines.push('')
                lines.push('-'.repeat(80))
            }
        }
        return lines
    }

    // Unknown format - show raw
    lines.push('')
    lines.push(`[Unparsed input format: ${typeof aiInput}]`)
    lines.push(JSON.stringify(aiInput).slice(0, 500))

    return lines
}

/**
 * Format output messages section
 */
export function formatOutputMessages(aiOutput: any, aiOutputChoices: any): string[] {
    const lines: string[] = []

    // Simple string output
    if (aiOutput && typeof aiOutput === 'string') {
        lines.push('')
        lines.push('OUTPUT:')
        lines.push('')
        const { lines: contentLines } = truncateContent(aiOutput)
        lines.push(...contentLines)
        return lines
    }

    // Extract choices array if wrapped in an object (e.g., xai format: {choices: [...]})
    let choices = aiOutputChoices
    if (aiOutputChoices && typeof aiOutputChoices === 'object' && !Array.isArray(aiOutputChoices)) {
        if ('choices' in aiOutputChoices && Array.isArray(aiOutputChoices.choices)) {
            choices = aiOutputChoices.choices
        }
    }

    // Output choices (most common format)
    if (choices && Array.isArray(choices) && choices.length > 0) {
        lines.push('')
        lines.push('OUTPUT:')

        for (let i = 0; i < choices.length; i++) {
            const choice = choices[i]

            // Handle different output choice formats
            let role: string
            let content: any
            let toolCalls: ToolCall[] = []

            if (typeof choice === 'string') {
                role = 'assistant'
                content = choice
            } else if ('message' in choice) {
                // Nested message format
                const msg = choice.message
                role = msg.role || msg.type || 'unknown'
                content = msg.content || ''
                toolCalls = msg.tool_calls || []
            } else {
                role = choice.role || choice.type || 'unknown'
                content = choice.content || ''
                toolCalls = choice.tool_calls || []
            }

            // Label tool messages specially
            const roleLabel = role.toLowerCase() === 'tool' ? 'TOOL RESULT' : role.toUpperCase()

            lines.push('')
            lines.push(`[${i + 1}] ${roleLabel}`)
            lines.push('')

            if (content || content === '') {
                const textContent = extractTextContent(content)
                if (textContent) {
                    const { lines: contentLines } = truncateContent(textContent)
                    lines.push(...contentLines)
                } else if (!toolCalls.length) {
                    lines.push('[empty response]')
                }
            }

            if (toolCalls.length > 0) {
                lines.push('')
                lines.push(...formatToolCalls(toolCalls))
            }

            // Add separator between messages (but not after the last one)
            if (i < choices.length - 1) {
                lines.push('')
                lines.push('-'.repeat(80))
            }
        }
    }

    return lines
}
