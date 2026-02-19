import { LLMProvider, LLMProviderKeyState, LLM_PROVIDER_LABELS } from './llmProviderKeysLogic'

const UNHEALTHY_PROVIDER_KEY_STATES = new Set<LLMProviderKeyState>(['invalid', 'error'])

export function isUnhealthyProviderKeyState(state: LLMProviderKeyState): boolean {
    return UNHEALTHY_PROVIDER_KEY_STATES.has(state)
}

export function providerKeyStateLabel(state: LLMProviderKeyState): string {
    switch (state) {
        case 'invalid':
            return 'Invalid'
        case 'error':
            return 'Error'
        case 'ok':
            return 'Valid'
        case 'unknown':
            return 'Unknown'
    }
}

export function providerKeyStateSuffix(state: LLMProviderKeyState): string {
    if (state === 'invalid') {
        return ' (Invalid)'
    }
    if (state === 'error') {
        return ' (Error)'
    }
    return ''
}

export function providerLabel(provider: LLMProvider): string {
    return LLM_PROVIDER_LABELS[provider]
}
