import { afterMount, kea, key, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { asDisplay } from 'scenes/persons/person-utils'
import { teamLogic } from 'scenes/teamLogic'
import { CyclotronJobInvocationGlobals, EventType, HogFunctionTemplateType, PersonType } from '~/types'

import type { hogFunctionStepLogicType } from './hogFunctionStepLogicType'

export function convertToHogFunctionInvocationGlobals(
    event: EventType,
    person: PersonType
): CyclotronJobInvocationGlobals {
    const team = teamLogic.findMounted()?.values?.currentTeam
    const projectUrl = `${window.location.origin}/project/${team?.id}`
    return {
        project: {
            id: team?.id ?? 0,
            name: team?.name ?? 'Default project',
            url: projectUrl,
        },
        event: {
            uuid: event.uuid ?? '',
            event: event.event,
            distinct_id: event.distinct_id,
            elements_chain: event.elements_chain ?? '',
            properties: event.properties,
            timestamp: event.timestamp,

            url: `${projectUrl}/events/${encodeURIComponent(event.uuid ?? '')}/${encodeURIComponent(event.timestamp)}`,
        },
        person: {
            id: person.uuid ?? '',
            properties: person.properties,

            name: asDisplay(person),
            url: `${projectUrl}/person/${encodeURIComponent(event.distinct_id)}`,
        },
        groups: {},
    }
}

export interface HogFunctionStepLogicProps {
    id?: string | null
    templateId?: string | null
}

export const hogFunctionStepLogic = kea<hogFunctionStepLogicType>([
    path(['products', 'messaging', 'frontend', 'Campaigns', 'hogflows', 'steps']),
    props({} as HogFunctionStepLogicProps),
    key(({ id, templateId }: HogFunctionStepLogicProps) => `${id}_${templateId}`),
    loaders(({ props }) => ({
        template: [
            null as HogFunctionTemplateType | null,
            {
                loadTemplate: async () => {
                    if (!props.templateId) {
                        return null
                    }

                    const res = await api.hogFunctions.getTemplate(props.templateId, true)

                    if (!res) {
                        throw new Error('Template not found')
                    }
                    return res
                },
            },
        ],
    })),
    afterMount(({ props, actions }) => {
        if (props.templateId) {
            actions.loadTemplate()
        }
    }),
])
