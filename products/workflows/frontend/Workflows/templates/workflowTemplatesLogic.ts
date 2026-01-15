import FuseClass from 'fuse.js'
import { actions, afterMount, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import type { HogFlowTemplate } from '../hogflows/types'
import type { workflowTemplatesLogicType } from './workflowTemplatesLogicType'

// Helping kea-typegen navigate the exported default class for Fuse
export interface Fuse extends FuseClass<HogFlowTemplate> {}

export const workflowTemplatesLogic = kea<workflowTemplatesLogicType>([
    path(['products', 'workflows', 'frontend', 'Workflows', 'workflowTemplatesLogic']),
    actions({
        setTemplateFilter: (search: string) => ({ search }),
        deleteHogflowTemplate: (template: HogFlowTemplate) => ({ template }),
    }),
    reducers({
        templateFilter: [
            '' as string,
            {
                setTemplateFilter: (_, { search }) => search,
            },
        ],
    }),
    loaders(({ values }) => ({
        workflowTemplates: [
            [] as HogFlowTemplate[],
            {
                loadWorkflowTemplates: async (): Promise<HogFlowTemplate[]> => {
                    const response = await api.hogFlowTemplates.getHogFlowTemplates()
                    return response.results as HogFlowTemplate[]
                },
                deleteHogflowTemplate: async ({ template }) => {
                    await api.hogFlowTemplates.deleteHogFlowTemplate(template.id)
                    return values.workflowTemplates.filter((t) => t.id !== template.id)
                },
            },
        ],
    })),
    selectors({
        workflowTemplateFuse: [
            (s) => [s.workflowTemplates],
            (workflowTemplates: HogFlowTemplate[]): Fuse => {
                return new FuseClass(workflowTemplates || [], {
                    keys: [{ name: 'name', weight: 2 }, 'description'],
                    threshold: 0.3,
                    ignoreLocation: true,
                })
            },
        ],
        filteredTemplates: [
            (s) => [s.workflowTemplates, s.templateFilter, s.workflowTemplateFuse],
            (
                workflowTemplates: HogFlowTemplate[],
                templateFilter: string,
                workflowTemplateFuse: Fuse
            ): HogFlowTemplate[] => {
                if (!templateFilter) {
                    return workflowTemplates
                }
                const searchResults = workflowTemplateFuse.search(templateFilter)
                return searchResults.map((result: { item: HogFlowTemplate }) => result.item)
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadWorkflowTemplates()
    }),
])
