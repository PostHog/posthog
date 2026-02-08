import { actions, afterMount, kea, listeners, path, reducers } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { ErrorTrackingSpikeDetectionConfig } from 'lib/components/Errors/types'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import type { spikeDetectionConfigLogicType } from './spikeDetectionConfigLogicType'

export interface SpikeDetectionConfigForm {
    snooze_duration_minutes: number
    multiplier: number
    threshold: number
}

const DEFAULT_CONFIG: SpikeDetectionConfigForm = {
    snooze_duration_minutes: 10,
    multiplier: 10,
    threshold: 500,
}

export const spikeDetectionConfigLogic = kea<spikeDetectionConfigLogicType>([
    path([
        'products',
        'error_tracking',
        'scenes',
        'ErrorTrackingConfigurationScene',
        'spike_detection',
        'spikeDetectionConfigLogic',
    ]),

    actions({
        setConfigValues: (config: SpikeDetectionConfigForm) => ({ config }),
    }),

    reducers({
        hasLoadedConfig: [
            false,
            {
                loadConfigSuccess: () => true,
            },
        ],
    }),

    loaders({
        config: [
            null as ErrorTrackingSpikeDetectionConfig | null,
            {
                loadConfig: async () => {
                    return await api.errorTracking.getSpikeDetectionConfig()
                },
            },
        ],
    }),

    forms(({ actions }) => ({
        configForm: {
            defaults: DEFAULT_CONFIG,
            errors: (formValues) => ({
                snooze_duration_minutes:
                    formValues.snooze_duration_minutes < 1 ? 'Snooze duration must be at least 1 minute' : undefined,
                multiplier: formValues.multiplier < 1 ? 'Multiplier must be at least 1' : undefined,
                threshold: formValues.threshold < 1 ? 'Threshold must be at least 1' : undefined,
            }),
            submit: async (formValues) => {
                try {
                    const updated = await api.errorTracking.updateSpikeDetectionConfig({
                        snooze_duration_minutes: formValues.snooze_duration_minutes,
                        multiplier: formValues.multiplier,
                        threshold: formValues.threshold,
                    })
                    actions.loadConfigSuccess(updated)
                    lemonToast.success('Spike detection settings saved')
                } catch (e) {
                    lemonToast.error('Failed to save spike detection settings')
                    throw e
                }
            },
        },
    })),

    listeners(({ actions }) => ({
        loadConfigSuccess: ({ config }) => {
            if (config) {
                actions.setConfigFormValues({
                    snooze_duration_minutes: config.snooze_duration_minutes,
                    multiplier: config.multiplier,
                    threshold: config.threshold,
                })
            }
        },
    })),

    afterMount(({ actions, values }) => {
        if (!values.hasLoadedConfig) {
            actions.loadConfig()
        }
    }),
])
