import { expectLogic } from 'kea-test-utils'

import { lemonToast } from '@posthog/lemon-ui'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import * as signalsApi from '../../generated/api'
import type { AlertPatternPreviewResponseApi, SignalSourceConfigApi } from '../../generated/api.schemas'
import { signalSourcesLogic } from '../signalSourcesLogic'
import { SignalSourceConfig, SignalSourceProduct, SignalSourceType } from '../types'
import { alertNamePatternsLogic } from './alertNamePatternsLogic'

const analyticsConfig: SignalSourceConfig = {
    id: 'config-analytics',
    source_product: SignalSourceProduct.Analytics,
    source_type: SignalSourceType.AnomalyInvestigation,
    enabled: true,
    // A key the patterns do not own, to prove a save merges rather than clobbers.
    config: { alert_scope: 'all_firing_alerts', alert_block_patterns: ['(?i)test'] },
    created_at: '2026-11-01T00:00:00Z',
    updated_at: '2026-11-01T00:00:00Z',
    status: null,
}

function previewResponse(overrides: Partial<AlertPatternPreviewResponseApi> = {}): AlertPatternPreviewResponseApi {
    return {
        alert_allow_patterns_error: null,
        alert_block_patterns_error: null,
        has_more: false,
        alerts: [
            {
                id: 'alert-1',
                name: 'Daily revenue',
                insight_name: 'Revenue',
                insight_short_id: 'abc',
                outcome: 'passed',
            },
            { id: 'alert-2', name: 'Test alert', insight_name: 'Revenue', insight_short_id: 'abc', outcome: 'blocked' },
        ],
        ...overrides,
    }
}

describe('alertNamePatternsLogic', () => {
    let logic: ReturnType<typeof alertNamePatternsLogic.build>
    let preview: jest.SpyInstance

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/signals/source_configs/': () => [
                    200,
                    { results: [analyticsConfig], count: 1, next: null, previous: null },
                ],
            },
        })
        initKeaTests()
        signalSourcesLogic.mount()
        signalSourcesLogic.actions.loadSourceConfigsSuccess([analyticsConfig])
        preview = jest
            .spyOn(signalsApi, 'signalsSourceConfigsAlertPatternPreviewCreate')
            .mockResolvedValue(previewResponse())
        logic = alertNamePatternsLogic({ sourceConfig: analyticsConfig })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    it('previews the typed patterns as they would be saved and blocks saving on an invalid one', async () => {
        await expectLogic(logic).toFinishAllListeners()

        preview.mockResolvedValue(previewResponse({ alert_allow_patterns_error: 'Pattern is not valid', alerts: [] }))
        logic.actions.setAllowText('  ^Daily \n\n(revenue')
        await expectLogic(logic).toFinishAllListeners()

        expect(preview).toHaveBeenLastCalledWith(expect.any(String), {
            alert_allow_patterns: ['^Daily', '(revenue'],
            alert_block_patterns: ['(?i)test'],
        })
        expect(logic.values.patternErrors).toEqual({ allow: 'Pattern is not valid', block: null })
        expect(logic.values.previewGroups).toBeNull()
        expect(logic.values.canSave).toBe(false)
    })

    it.each([
        { outcome: 'saves the patterns', fails: false, hasChanges: false, savedAllow: ['^Daily'] },
        { outcome: 'keeps the edit unsaved when the save fails', fails: true, hasChanges: true, savedAllow: [] },
    ])('$outcome', async ({ fails, hasChanges, savedAllow }) => {
        const update = jest.spyOn(signalsApi, 'signalsSourceConfigsPartialUpdate').mockImplementation(async () => {
            if (fails) {
                throw { detail: 'Request failed.' }
            }
            return {
                ...analyticsConfig,
                config: { ...analyticsConfig.config, alert_allow_patterns: ['^Daily'] },
            } as SignalSourceConfigApi
        })
        jest.spyOn(lemonToast, 'error').mockImplementation(() => 'toast')
        logic.actions.setAllowText('^Daily\n')
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.canSave).toBe(true)

        logic.actions.save()
        await expectLogic(logic).toFinishAllListeners()

        expect(update).toHaveBeenCalledWith(expect.any(String), 'config-analytics', {
            config_set: { alert_allow_patterns: ['^Daily'], alert_block_patterns: ['(?i)test'] },
        })
        expect(logic.values.savedAllowPatterns).toEqual(savedAllow)
        expect(logic.values.hasChanges).toBe(hasChanges)
        expect(logic.values.saving).toBe(false)
        expect(signalSourcesLogic.values.anomalyInvestigationConfig?.config.alert_scope).toBe('all_firing_alerts')
    })

    it('shows the preview as failed when it cannot load', async () => {
        preview.mockRejectedValue({ status: 500, detail: 'A server error occurred.' })

        logic.actions.loadPreview()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.previewFailed).toBe(true)
        expect(logic.values.previewLoading).toBe(false)
    })
})
