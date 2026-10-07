import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { FeatureFlagConfig } from '~/types'

import {
    canRestoreFeatureFlag,
    featureFlagConfigFormat,
    featureFlagConfigFormatLabel,
    featureFlagDeleteOptions,
    rowVersionToken,
} from './featureFlagConfigFormat'

describe('featureFlagConfigFormat', () => {
    it.each([
        [undefined, 'v1', 'Config v1'],
        [{ groups: [] }, 'v1', 'Config v1'],
        [{ version: 1, groups: [] }, 'v1', 'Config v1'],
        [{ version: 2, return_type: 'boolean', default_value: false, rules: [] }, 'v2', 'Rules v2'],
        [{ version: 3 }, 'unsupported', 'Config v3 (unsupported)'],
        [{ version: null }, 'unsupported', 'Unsupported config'],
        [{ version: '2' }, 'unsupported', 'Unsupported config'],
    ])('reads %j as %s', (filters, format, label) => {
        expect(featureFlagConfigFormat(filters as FeatureFlagConfig | undefined)).toBe(format)
        expect(featureFlagConfigFormatLabel(filters as FeatureFlagConfig | undefined)).toBe(label)
    })

    it.each([
        ['a v1 row', { filters: { groups: [] }, version: 4 }, {}],
        ['a v2 row', { filters: { version: 2 } as FeatureFlagConfig, version: 4 }, { version: 4 }],
        ['an unsupported row', { filters: { version: 3 }, version: 4 }, { version: 4 }],
        ['a v2 row written before versioning', { filters: { version: 2 } as FeatureFlagConfig, version: null }, {}],
    ])('sends the row version only for a row outside v1: %s', (_, flag, expected) => {
        expect(rowVersionToken(flag)).toEqual(expected)
    })

    it.each([
        [undefined, true],
        [{ groups: [] }, true],
        [{ version: 2 }, false],
        [{ version: 3 }, false],
    ])('allows restoring %j: %s', (filters, expected) => {
        expect(canRestoreFeatureFlag(filters as FeatureFlagConfig | undefined)).toBe(expected)
    })
})

describe('featureFlagDeleteOptions', () => {
    const stale = { status: 409, detail: 'This feature flag has changed.' }

    beforeEach(() => {
        jest.spyOn(lemonToast, 'error').mockImplementation(() => 'toast-id')
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('sends no row version for a v1 flag, offers Undo and leaves a 409 to the error toast', () => {
        const reload = jest.fn()
        const options = featureFlagDeleteOptions({ filters: { groups: [] }, version: 4 }, reload)

        expect(options.payload).toEqual({})
        expect(options.undoable).toBe(true)
        expect(options.onError(stale)).toBe(false)
        expect(reload).not.toHaveBeenCalled()
    })

    it('sends the row version for a v2 flag, offers no Undo and reloads on a stale row version', () => {
        const reload = jest.fn()
        const options = featureFlagDeleteOptions({ filters: { version: 2 } as FeatureFlagConfig, version: 4 }, reload)

        expect(options.payload).toEqual({ version: 4 })
        expect(options.undoable).toBe(false)
        expect(options.onError({ status: 400, detail: 'Bad request' })).toBe(false)
        expect(reload).not.toHaveBeenCalled()
        expect(options.onError(stale)).toBe(true)
        expect(reload).toHaveBeenCalledTimes(1)
        expect(lemonToast.error).toHaveBeenCalledWith('This feature flag has changed.')
    })
})
