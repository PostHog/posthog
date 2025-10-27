import { afterMount, kea, path } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { isDefinitionStale } from 'lib/utils/definitions'

import { EventDefinitionType } from '~/types'

import type { exceptionIngestionLogicType } from './exceptionIngestionLogicType'

export const exceptionIngestionLogic = kea<exceptionIngestionLogicType>([
    path(['products', 'error_tracking', 'components', 'SetupPrompt', 'exceptionIngestionLogic']),
    loaders({
        hasSentExceptionEvent: {
            __default: undefined as boolean | undefined,
            loadExceptionEventDefinition: async (): Promise<boolean> => {
                const exceptionDefinition = await api.eventDefinitions.list({
                    event_type: EventDefinitionType.Event,
                    search: '$exception',
                })
                const definition = exceptionDefinition.results.find((r) => r.name === '$exception')
                return definition ? !isDefinitionStale(definition) : false
            },
        },
    }),

    afterMount(({ actions }) => {
        actions.loadExceptionEventDefinition()
    }),
])
