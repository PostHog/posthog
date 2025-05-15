import { actions, connect, events, kea, listeners, path, props, reducers, selectors } from 'kea'
import api from 'lib/api'

import { StreamConfigEvent, StreamConfigEventProperty } from '~/types'

import type { visionHogConfigLogicType } from './visionHogConfiglogicType'
import { visionHogSceneLogic } from './visionHogSceneLogic'

export interface VisionHogConfigLogicProps {
    // Define any props your logic might need here
    // exampleProp?: string
}

export enum ConfigState {
    CREATE = 'create',
    EDIT = 'edit',
}

export const visionHogConfigLogic = kea<visionHogConfigLogicType>([
    path(['products', 'visionHog', 'frontend', 'visionHogConfigLogic']),
    props({} as VisionHogConfigLogicProps), // Pass empty props object for now

    connect(() => ({
        values: [visionHogSceneLogic, ['targetStreamConfig']],
        actions: [visionHogSceneLogic, ['loadStreamConfigs', 'setActiveTab']],
    })),
    actions({
        getConfigSuggestion: (prompt: string) => ({ prompt }),
        setSuggestions: (suggestions: StreamConfigEvent[]) => ({ suggestions }),
        removeSuggestion: (index: number) => ({ index }),
        updateSuggestion: (index: number, updatedEvent: Partial<StreamConfigEvent>) => ({ index, updatedEvent }),
        setSuggestionsLoading: (loading: boolean) => ({ loading }),
        addEmptySuggestion: () => ({}),
        setUrl: (url: string) => ({ url }),
        saveStreamConfig: true,
        addPropertyToEvent: (eventIndex: number) => ({ eventIndex }),
        updateEventProperty: (
            eventIndex: number,
            propertyIndex: number,
            updates: Partial<StreamConfigEventProperty>
        ) => ({
            eventIndex,
            propertyIndex,
            updates,
        }),
        removeEventProperty: (eventIndex: number, propertyIndex: number) => ({ eventIndex, propertyIndex }),
    }),

    reducers({
        url: ['', { setUrl: (_, { url }) => url }],
        suggestions: [
            [] as StreamConfigEvent[],
            {
                setSuggestions: (_, { suggestions }) => suggestions,
                removeSuggestion: (state, { index }) => state.filter((_, i) => i !== index),
                updateSuggestion: (state, { index, updatedEvent }) =>
                    state.map((event, i) => (i === index ? { ...event, ...updatedEvent } : event)),
                addEmptySuggestion: (state) => [...state, { name: '', description: '', properties: [] }],
                addPropertyToEvent: (state, { eventIndex }) => {
                    const newState = [...state]
                    if (newState[eventIndex]) {
                        newState[eventIndex].properties = [
                            ...newState[eventIndex].properties,
                            { name: '', description: '' },
                        ]
                    }
                    return newState
                },
                updateEventProperty: (state, { eventIndex, propertyIndex, updates }) => {
                    const newState = [...state]
                    if (newState[eventIndex]?.properties?.[propertyIndex]) {
                        newState[eventIndex].properties[propertyIndex] = {
                            ...newState[eventIndex].properties[propertyIndex],
                            ...updates,
                        }
                    }
                    return newState
                },
                removeEventProperty: (state, { eventIndex, propertyIndex }) => {
                    const newState = [...state]
                    if (newState[eventIndex]) {
                        newState[eventIndex].properties = newState[eventIndex].properties.filter(
                            (_, i) => i !== propertyIndex
                        )
                    }
                    return newState
                },
            },
        ],
        suggestionsLoading: [false, { setSuggestionsLoading: (_, { loading }) => loading }],
    }),

    listeners(({ values, actions }) => ({
        getConfigSuggestion: async ({ prompt }) => {
            actions.setSuggestionsLoading(true)
            const response = await api.streamConfig.getConfigSuggestion(prompt)
            // Convert string suggestions to EventConfig objects
            const newEventConfigs = response.suggestions.map((suggestion: StreamConfigEvent) => ({
                name: suggestion.name,
                description: suggestion.description,
                properties: suggestion.properties,
            }))
            actions.setSuggestions([...values.suggestions, ...newEventConfigs])
            actions.setSuggestionsLoading(false)
        },
        saveStreamConfig: async () => {
            // Convert EventConfig objects to the format expected by the API
            const simplifiedEvents = values.suggestions.map((event) => ({
                name: event.name,
                description: event.description,
                properties: event.properties,
            }))

            if (values.configState === ConfigState.CREATE) {
                await api.streamConfig.create({
                    stream_url: values.url,
                    events: simplifiedEvents,
                })
            } else {
                await api.streamConfig.update(values.targetStreamConfig.id, {
                    stream_url: values.url,
                    events: simplifiedEvents,
                })
            }
            actions.setActiveTab('video')
            actions.loadStreamConfigs()
        },
    })),
    selectors({
        configState: [
            (s) => [s.targetStreamConfig],
            (targetStreamConfig) =>
                targetStreamConfig && targetStreamConfig.id ? ConfigState.EDIT : ConfigState.CREATE,
        ],
    }),
    events(({ values, actions }) => ({
        afterMount() {
            if (values.targetStreamConfig) {
                actions.setUrl(values.targetStreamConfig.stream_url)

                // Handle loading existing events - convert from API format if needed
                const events = values.targetStreamConfig.events || []
                const eventConfigs = Array.isArray(events)
                    ? events.map((event) => {
                          if (typeof event === 'string') {
                              // Handle old format (strings)
                              return { name: event, description: '', properties: [] }
                          }
                          // Handle new format (objects)
                          return {
                              name: event.name || '',
                              description: event.description || '',
                              properties: Array.isArray(event.properties) ? event.properties : [],
                          }
                      })
                    : []

                actions.setSuggestions(eventConfigs)
            }
        },
    })),
])
