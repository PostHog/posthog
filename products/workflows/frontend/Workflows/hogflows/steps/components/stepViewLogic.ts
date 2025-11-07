import { kea } from 'kea'

import { HogFlowAction } from '../../types'
import type { stepViewLogicType } from './stepViewLogicType'

export type StepViewLogicProps = {
    action: HogFlowAction
}

export const stepViewLogic = kea<stepViewLogicType>({
    path: (key) => [
        'products',
        'workflows',
        'frontend',
        'Workflows',
        'hogflows',
        'steps',
        'components',
        'stepViewLogic',
        key,
    ],
    key: ({ action }: StepViewLogicProps) => action.id,
    props: {} as StepViewLogicProps,
    actions: {
        startEditingName: true,
        startEditingDescription: true,
        setEditNameValue: (value: string) => ({ value }),
        setEditDescriptionValue: (value: string) => ({ value }),
        saveName: true,
        saveDescription: true,
        cancelEditingName: true,
        cancelEditingDescription: true,
    },
    reducers: ({ props }) => ({
        isEditingName: [
            false,
            {
                startEditingName: () => true,
                saveName: () => false,
                cancelEditingName: () => false,
            },
        ],
        isEditingDescription: [
            false,
            {
                startEditingDescription: () => true,
                saveDescription: () => false,
                cancelEditingDescription: () => false,
            },
        ],
        editNameValue: [
            props.action.name,
            {
                setEditNameValue: (_, { value }) => value,
                saveName: (state) => state, // Keep the current value until props update
                cancelEditingName: () => props.action.name,
            },
        ],
        editDescriptionValue: [
            props.action.description || '',
            {
                setEditDescriptionValue: (_, { value }) => value,
                saveDescription: (state) => state, // Keep the current value until props update
                cancelEditingDescription: () => props.action.description || '',
            },
        ],
    }),
    propsChanged: ({ actions, props, values }: { actions: any; props: StepViewLogicProps; values: any }) => {
        // Sync edit values when action changes (but only if not currently editing)
        if (!values.isEditingName && values.editNameValue !== props.action.name) {
            actions.setEditNameValue(props.action.name)
        }
        if (!values.isEditingDescription && values.editDescriptionValue !== (props.action.description || '')) {
            actions.setEditDescriptionValue(props.action.description || '')
        }
    },
})
