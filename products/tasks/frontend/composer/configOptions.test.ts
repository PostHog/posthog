import type { AcpMessage, SessionConfigOption } from '../conversation/acp-types'
import {
    cycleModeOption,
    deriveConfigOptions,
    flattenSelectOptions,
    getConfigOptionByCategory,
    isSelectGroup,
    visibleModeOptions,
} from './configOptions'

function configUpdateEvent(configOptions: SessionConfigOption[], ts = 1): AcpMessage {
    return {
        type: 'acp_message',
        ts,
        message: {
            jsonrpc: '2.0',
            method: 'session/update',
            params: { sessionId: 's1', update: { sessionUpdate: 'config_option_update', configOptions } },
        },
    }
}

const modeOption: SessionConfigOption = {
    type: 'select',
    id: 'mode',
    name: 'Mode',
    category: 'mode',
    currentValue: 'default',
    options: [
        { value: 'plan', name: 'Plan' },
        { value: 'default', name: 'Default' },
        { value: 'acceptEdits', name: 'Accept edits' },
        { value: 'bypassPermissions', name: 'Bypass' },
    ],
}

const modelOption: SessionConfigOption = {
    type: 'select',
    id: 'model',
    name: 'Model',
    category: 'model',
    currentValue: 'sonnet',
    options: [
        {
            group: 'claude',
            name: 'Claude',
            options: [
                { value: 'opus', name: 'Opus' },
                { value: 'sonnet', name: 'Sonnet' },
            ],
        },
    ],
}

describe('configOptions', () => {
    describe('isSelectGroup / flattenSelectOptions', () => {
        it('flattens flat options unchanged', () => {
            const flat = [{ value: 'a', name: 'A' }]
            expect(isSelectGroup(flat)).toBe(false)
            expect(flattenSelectOptions(flat)).toEqual(flat)
        })

        it('flattens grouped options', () => {
            expect(isSelectGroup(modelOption.type === 'select' ? modelOption.options : [])).toBe(true)
            const flat = flattenSelectOptions(modelOption.type === 'select' ? modelOption.options : [])
            expect(flat.map((o) => o.value)).toEqual(['opus', 'sonnet'])
        })

        it('returns [] for empty options', () => {
            expect(flattenSelectOptions([])).toEqual([])
        })
    })

    describe('getConfigOptionByCategory', () => {
        it('finds the option by category', () => {
            expect(getConfigOptionByCategory([modeOption, modelOption], 'model')?.id).toBe('model')
        })
        it('returns undefined when missing', () => {
            expect(getConfigOptionByCategory([modeOption], 'thought_level')).toBeUndefined()
            expect(getConfigOptionByCategory(undefined, 'mode')).toBeUndefined()
        })
    })

    describe('visibleModeOptions', () => {
        it('hides bypass modes by default', () => {
            const visible = visibleModeOptions(modeOption as never, false).map((o) => o.value)
            expect(visible).toEqual(['plan', 'default', 'acceptEdits'])
        })
        it('shows bypass modes when allowed', () => {
            const visible = visibleModeOptions(modeOption as never, true).map((o) => o.value)
            expect(visible).toContain('bypassPermissions')
        })
    })

    describe('cycleModeOption', () => {
        it('cycles to the next non-bypass mode', () => {
            expect(cycleModeOption(modeOption)).toBe('acceptEdits')
        })
        it('wraps around skipping bypass modes', () => {
            expect(cycleModeOption({ ...modeOption, currentValue: 'acceptEdits' } as SessionConfigOption)).toBe('plan')
        })
        it('returns undefined for a non-select option', () => {
            expect(cycleModeOption(undefined)).toBeUndefined()
        })
    })

    describe('deriveConfigOptions', () => {
        it('returns [] when no config update present', () => {
            expect(deriveConfigOptions([])).toEqual([])
        })
        it('returns the latest config option set', () => {
            const first = configUpdateEvent([modeOption], 1)
            const second = configUpdateEvent([{ ...modeOption, currentValue: 'plan' }, modelOption], 2)
            expect(deriveConfigOptions([first, second])).toHaveLength(2)
            expect((deriveConfigOptions([first, second])[0] as { currentValue: string }).currentValue).toBe('plan')
        })
        it('ignores non-session-update notifications', () => {
            const noise: AcpMessage = {
                type: 'acp_message',
                ts: 1,
                message: { jsonrpc: '2.0', method: '_posthog/console', params: {} },
            }
            expect(deriveConfigOptions([noise])).toEqual([])
        })
    })
})
