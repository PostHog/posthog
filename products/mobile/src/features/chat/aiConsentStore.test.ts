import AsyncStorage from '@react-native-async-storage/async-storage'

import { useAuthStore } from '@/auth/authStore'

import { aiConsentKey, useAiConsentStore } from './aiConsentStore'

describe('AI consent store', () => {
    test('the broader AI disclosure requires new consent after an older chat-only consent', async () => {
        await AsyncStorage.setItem(
            'posthog-mobile-ai-consent',
            JSON.stringify({ version: 0, state: { accepted: { 'https://app.example.com|person': true } } })
        )
        await useAiConsentStore.persist.rehydrate()
        expect(useAiConsentStore.getState().accepted).toEqual({})
    })

    test('consent covers only the person and host that gave it', () => {
        useAiConsentStore.getState().accept(aiConsentKey('https://us.posthog.com', 'user-a'))

        const { accepted } = useAiConsentStore.getState()
        expect(accepted[aiConsentKey('https://us.posthog.com', 'user-a')]).toBe(true)
        expect(accepted[aiConsentKey('https://us.posthog.com', 'user-b')]).toBeUndefined()
        expect(accepted[aiConsentKey('https://eu.posthog.com', 'user-a')]).toBeUndefined()
    })

    test('sign out drops every stored consent', async () => {
        useAiConsentStore.getState().accept(aiConsentKey('https://us.posthog.com', 'user-a'))

        await useAuthStore.getState().signOut()

        expect(useAiConsentStore.getState().accepted).toEqual({})
    })
})
