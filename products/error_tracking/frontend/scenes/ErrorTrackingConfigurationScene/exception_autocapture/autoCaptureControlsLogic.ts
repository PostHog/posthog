import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { ErrorTrackingAutoCaptureControls, Trigger, TriggerType } from 'lib/components/IngestionControls/types'

import type { autoCaptureControlsLogicType } from './autoCaptureControlsLogicType'

export const autoCaptureControlsLogic = kea<autoCaptureControlsLogicType>([
    path([
        'products',
        'error_tracking',
        'frontend',
        'scenes',
        'ErrorTrackingConfigurationScene',
        'exception_autocapture',
        'autoCaptureControlsLogic',
    ]),
    actions({
        setMatchType: (matchType: ErrorTrackingAutoCaptureControls['match_type']) => ({ matchType }),
        setSampleRate: (sampleRate: ErrorTrackingAutoCaptureControls['sample_rate']) => ({ sampleRate }),
        setLinkedFeatureFlag: (linkedFeatureFlag: ErrorTrackingAutoCaptureControls['linked_feature_flag']) => ({
            linkedFeatureFlag,
        }),
        setEventTriggers: (eventTriggers: ErrorTrackingAutoCaptureControls['event_triggers']) => ({ eventTriggers }),
        setUrlTriggers: (urlTriggers: ErrorTrackingAutoCaptureControls['url_triggers']) => ({ urlTriggers }),
        setUrlBlocklist: (urlBlocklist: ErrorTrackingAutoCaptureControls['url_blocklist']) => ({ urlBlocklist }),
    }),
    reducers({
        matchType: [
            'all' as ErrorTrackingAutoCaptureControls['match_type'],
            {
                setMatchType: (_, { matchType }) => matchType,
                loadControlsSuccess: (_, { controls }) => controls?.match_type ?? 'all',
            },
        ],
        sampleRate: [
            1 as ErrorTrackingAutoCaptureControls['sample_rate'],
            {
                setSampleRate: (_, { sampleRate }) => sampleRate,
                loadControlsSuccess: (_, { controls }) => controls?.sample_rate ?? 1,
            },
        ],
        linkedFeatureFlag: [
            null as ErrorTrackingAutoCaptureControls['linked_feature_flag'],
            {
                setLinkedFeatureFlag: (_, { linkedFeatureFlag }) => linkedFeatureFlag,
                loadControlsSuccess: (_, { controls }) => controls?.linked_feature_flag ?? null,
            },
        ],
        eventTriggers: [
            [] as ErrorTrackingAutoCaptureControls['event_triggers'],
            {
                setEventTriggers: (_, { eventTriggers }) => eventTriggers,
                loadControlsSuccess: (_, { controls }) => controls?.event_triggers ?? [],
            },
        ],
        urlTriggers: [
            [] as ErrorTrackingAutoCaptureControls['url_triggers'],
            {
                setUrlTriggers: (_, { urlTriggers }) => urlTriggers,
                loadControlsSuccess: (_, { controls }) => controls?.url_triggers ?? [],
            },
        ],
        urlBlocklist: [
            [] as ErrorTrackingAutoCaptureControls['url_blocklist'],
            {
                setUrlBlocklist: (_, { urlBlocklist }) => urlBlocklist,
                loadControlsSuccess: (_, { controls }) => controls?.url_blocklist ?? [],
            },
        ],
    }),
    loaders(({ values }) => ({
        controls: [
            null as ErrorTrackingAutoCaptureControls | null,
            {
                loadControls: async () => {
                    return await api.errorTracking.autoCaptureControls.get()
                },
                createControls: async () => {
                    return await api.errorTracking.autoCaptureControls.create()
                },
                saveControls: async () => {
                    if (values.controls) {
                        const newControls: ErrorTrackingAutoCaptureControls = {
                            id: values.controls.id,
                            library: values.controls.library,
                            match_type: values.matchType,
                            sample_rate: values.sampleRate,
                            linked_feature_flag: values.linkedFeatureFlag,
                            event_triggers: values.eventTriggers,
                            url_triggers: values.urlTriggers,
                            url_blocklist: values.urlBlocklist,
                        }
                        return await api.errorTracking.autoCaptureControls.update(newControls)
                    }
                    return values.controls
                },
                deleteControls: async () => {
                    if (values.controls) {
                        await api.errorTracking.autoCaptureControls.delete(values.controls.id)
                    }
                    return null
                },
            },
        ],
    })),
    selectors({
        triggers: [
            (s) => [s.sampleRate, s.linkedFeatureFlag, s.eventTriggers, s.urlTriggers],
            (sampleRate, linkedFeatureFlag, eventTriggers, urlTriggers): Trigger[] => [
                {
                    type: TriggerType.URL_MATCH,
                    enabled: urlTriggers.length > 0,
                    urls: urlTriggers,
                },
                {
                    type: TriggerType.EVENT,
                    enabled: eventTriggers.length > 0,
                    events: eventTriggers,
                },
                {
                    type: TriggerType.FEATURE_FLAG,
                    enabled: !!linkedFeatureFlag,
                    key: linkedFeatureFlag?.key ?? null,
                },
                {
                    type: TriggerType.SAMPLING,
                    enabled: sampleRate < 1,
                    sampleRate: sampleRate,
                },
            ],
        ],
        hasControls: [(s) => [s.controls], (controls) => controls !== null],
    }),
    listeners(({ actions }) => ({
        setMatchType: () => actions.saveControls(),
        setSampleRate: () => actions.saveControls(),
        setLinkedFeatureFlag: () => actions.saveControls(),
        setEventTriggers: () => actions.saveControls(),
        setUrlTriggers: () => actions.saveControls(),
        setUrlBlocklist: () => actions.saveControls(),
    })),
])
