export interface RoleBasedMessage {
    role: string
    content: string | { type: string; content: string }
}

export interface OpenAIToolCall {
    type: string
    id?: string
    function: {
        name: string
        arguments: string
    }
}

export interface OpenAICompletionMessage extends RoleBasedMessage {
    tool_calls?: Record<string, any>[]
    [additionalKey: string]: any
}

export interface AnthropicTextMessage {
    type: 'text'
    text: string
}

export interface VercelSDKTextMessage {
    type: 'text'
    content: string
}

export interface VercelSDKImageMessage {
    type: 'image'
    image: string
}

export interface AnthropicToolCallMessage {
    type: 'tool_use'
    id: string
    name: string
    input: Record<string, any>
}

export interface AnthropicThinkingMessage {
    type: 'thinking'
    thinking: string
    signature: string
}

export interface AnthropicToolResultMessage {
    type: 'tool_result'
    tool_use_id: string
    content: string | AnthropicTextMessage[]
}

export type AnthropicCompletionMessage = AnthropicTextMessage | AnthropicToolCallMessage | AnthropicToolResultMessage

export interface AnthropicInputMessage {
    role: string
    content: string | AnthropicCompletionMessage[]
}

export type InputMessage = OpenAICompletionMessage | AnthropicInputMessage
export type CompletionMessage = OpenAICompletionMessage | AnthropicCompletionMessage

export interface CompatToolCall {
    type: string
    id?: string
    function: {
        name: string
        arguments: Record<string, any>
    }
}

export interface CompatMessage extends RoleBasedMessage {
    tool_calls?: CompatToolCall[]
    [additionalKey: string]: any
    tool_call_id?: string
}
