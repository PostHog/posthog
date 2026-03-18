export interface RoleBasedMessage {
    role: string
    content: string | { type: string; content: string } | MultiModalContentItem[]
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

export interface VercelSDKInputImageMessage {
    type: 'input_image'
    image_url: string
}

export interface OpenAIImageURLMessage {
    type: 'image_url'
    image_url: {
        url: string
    }
}

export interface OpenAIFileMessage {
    type: 'file'
    file: {
        file_data: string
        filename: string
    }
}

export interface OpenAIAudioMessage {
    type: 'audio'
    data: string
    transcript: string
    id: string
    expires_at: number
}

export interface AnthropicImageMessage {
    type: 'image'
    source: {
        type: 'base64'
        media_type: string
        data: string
    }
}

export interface AnthropicDocumentMessage {
    type: 'document'
    source: {
        type: 'base64'
        media_type: string
        data: string
    }
}

export interface GeminiAudioMessage {
    type: 'audio'
    data: string
    mime_type: string
}

export interface GeminiImageMessage {
    type: 'image'
    // snake_case (Python SDK)
    inline_data?: {
        data: string
        mime_type: string
    }
    // camelCase (Node SDK)
    inlineData?: {
        data: string
        mimeType: string
    }
}

export interface GeminiDocumentMessage {
    type: 'document' | 'image' // 'image' when SDK misdetects PDF by MIME type
    // snake_case (Python SDK)
    inline_data?: {
        data: string
        mime_type: string
    }
    // camelCase (Node SDK)
    inlineData?: {
        data: string
        mimeType: string
    }
}

export interface VercelSDKInputTextMessage {
    type: 'input_text'
    text: string
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
        arguments: Record<string, any> | string // Allow string for unparsed/malformed JSON
    }
}

export interface CompatMessage extends RoleBasedMessage {
    tool_calls?: CompatToolCall[]
    [additionalKey: string]: any
    tool_call_id?: string
}

export interface LiteLLMChoice {
    finish_reason: string
    index: number
    message: {
        annotations?: any[]
        content: string | null
        function_call?: any
        role: string
        tool_calls?: any[] | null
    }
    provider_specific_fields?: Record<string, any>
}

export interface LiteLLMResponse {
    choices?: LiteLLMChoice[]
    [additionalKey: string]: any
}

export interface TextContentItem {
    type: 'text'
    text: string
}

export interface ImageContentItem {
    type: 'image'
    image: string
}

export type MultiModalContentItem =
    | string
    | TextContentItem
    | ImageContentItem
    | OpenAIImageURLMessage
    | OpenAIFileMessage
    | OpenAIAudioMessage
    | AnthropicImageMessage
    | AnthropicDocumentMessage
    | GeminiImageMessage
    | GeminiDocumentMessage
    | GeminiAudioMessage
