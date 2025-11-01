/**
 * Message format detection and normalization
 * Handles different LLM provider message structures
 */
import { isObject } from 'lib/utils'

export enum MessageFormat {
    // OpenAI-style: { role: "user", content: "text", tool_calls?: [...] }
    OPENAI_STANDARD = 'openai_standard',

    // Anthropic-style: { type: "human", content: [{ type: "text", text: "..." }] }
    ANTHROPIC_BLOCKS = 'anthropic_blocks',

    // LangChain-style: nested content with state objects
    LANGCHAIN_STATE = 'langchain_state',

    // Tool call format: { type: "tool-call", function: {...} }
    TOOL_CALL = 'tool_call',

    // Simple string
    SIMPLE_STRING = 'simple_string',

    // Unknown/complex structure
    UNKNOWN = 'unknown',
}

/**
 * Detect the format of a message or content object
 */
export function detectMessageFormat(content: any): MessageFormat {
    if (typeof content === 'string') {
        return MessageFormat.SIMPLE_STRING
    }

    if (!isObject(content)) {
        return MessageFormat.UNKNOWN
    }

    // Check for tool call format
    if ('type' in content && content.type === 'tool-call' && 'function' in content) {
        return MessageFormat.TOOL_CALL
    }

    // Check for Anthropic blocks format (array of typed blocks)
    if (Array.isArray(content)) {
        const hasTypedBlocks = content.some((item) => isObject(item) && 'type' in item)
        if (hasTypedBlocks) {
            return MessageFormat.ANTHROPIC_BLOCKS
        }
    }

    // Check for OpenAI standard format
    if ('role' in content && ('content' in content || 'tool_calls' in content)) {
        return MessageFormat.OPENAI_STANDARD
    }

    // Check for direct text property (Anthropic single block)
    if ('text' in content && 'type' in content) {
        return MessageFormat.ANTHROPIC_BLOCKS
    }

    // Check for LangChain state format (nested content with state properties)
    if ('content' in content && isObject(content.content)) {
        const nestedContent = content.content
        const hasStateKeys = Object.keys(nestedContent).some((key) =>
            ['toolName', 'args', 'result', 'messages', 'intermediate_steps'].includes(key)
        )
        if (hasStateKeys) {
            return MessageFormat.LANGCHAIN_STATE
        }
    }

    return MessageFormat.UNKNOWN
}

/**
 * Extract text from content based on detected format
 */
export function extractTextByFormat(content: any, format: MessageFormat): string | null {
    switch (format) {
        case MessageFormat.SIMPLE_STRING:
            return content

        case MessageFormat.OPENAI_STANDARD:
            if (typeof content.content === 'string') {
                return content.content
            }
            // OpenAI can also have array content
            if (Array.isArray(content.content)) {
                return extractFromAnthropicBlocks(content.content)
            }
            return null

        case MessageFormat.ANTHROPIC_BLOCKS:
            if (Array.isArray(content)) {
                return extractFromAnthropicBlocks(content)
            }
            if ('text' in content && typeof content.text === 'string') {
                return content.text
            }
            return null

        case MessageFormat.LANGCHAIN_STATE:
            if ('content' in content) {
                return extractTextRecursive(content.content)
            }
            return null

        case MessageFormat.TOOL_CALL:
            // Tool calls don't have text content
            return null

        case MessageFormat.UNKNOWN:
        default:
            // Fallback to recursive extraction
            return extractTextRecursive(content)
    }
}

/**
 * Extract text from Anthropic-style blocks array
 */
function extractFromAnthropicBlocks(blocks: any[]): string | null {
    const textParts: string[] = []

    for (const block of blocks) {
        if (!isObject(block)) {
            continue
        }

        // Skip tool-call blocks
        if ('type' in block && block.type === 'tool-call') {
            continue
        }

        // Extract text from text blocks
        if ('text' in block && typeof block.text === 'string') {
            textParts.push(block.text)
        }

        // Handle nested content
        if ('content' in block) {
            const nested = extractTextRecursive(block.content)
            if (nested) {
                textParts.push(nested)
            }
        }
    }

    return textParts.length > 0 ? textParts.join('\n') : null
}

/**
 * Recursive text extraction as fallback for unknown formats
 */
function extractTextRecursive(content: any, depth = 0): string | null {
    // Prevent infinite recursion
    if (depth > 10) {
        return null
    }

    if (typeof content === 'string') {
        return content
    }

    if (!isObject(content)) {
        return null
    }

    // Try direct text property
    if ('text' in content && typeof content.text === 'string') {
        return content.text
    }

    // Try direct content property
    if ('content' in content) {
        if (typeof content.content === 'string') {
            return content.content
        }
        return extractTextRecursive(content.content, depth + 1)
    }

    // Try array
    if (Array.isArray(content)) {
        const parts: string[] = []
        for (const item of content) {
            const text = extractTextRecursive(item, depth + 1)
            if (text) {
                parts.push(text)
            }
        }
        return parts.length > 0 ? parts.join('\n') : null
    }

    return null
}

/**
 * Extract tool calls from various formats
 */
export function extractToolCalls(content: any): Array<{ name: string; arguments: any }> {
    const toolCalls: Array<{ name: string; arguments: any }> = []

    // OpenAI format: message.tool_calls array
    if (isObject(content) && 'tool_calls' in content && Array.isArray(content.tool_calls)) {
        for (const tc of content.tool_calls) {
            if (tc.function) {
                toolCalls.push({
                    name: tc.function.name || 'unknown',
                    arguments: tc.function.arguments || ('' as any),
                })
            }
        }
        return toolCalls
    }

    // Anthropic/LangChain format: blocks with type="tool-call"
    if (Array.isArray(content)) {
        for (const block of content) {
            if (isObject(block) && 'type' in block && block.type === 'tool-call') {
                if ('function' in block && isObject(block.function)) {
                    const func = block.function as any
                    toolCalls.push({
                        name: func.name || 'unknown',
                        arguments: func.arguments || '',
                    })
                }
            }
        }
    }

    return toolCalls
}

/**
 * Safe extraction with fallback for unparseable content
 */
export function safeExtractText(content: any): string {
    const format = detectMessageFormat(content)
    const text = extractTextByFormat(content, format)

    if (text !== null && text.trim() !== '') {
        return text
    }

    // Fallback: show format type and indicate parsing issue
    return `[UNABLE_TO_PARSE: format=${format}, type=${typeof content}]`
}
