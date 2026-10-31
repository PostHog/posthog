import type { Meta, StoryObj } from '@storybook/react'

import { NodeKind } from '~/queries/schema/schema-general'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { NegatedEventFilterNote } from './NegatedEventFilterNote'

const meta: Meta<typeof NegatedEventFilterNote> = {
    title: 'Experiments/NegatedEventFilterNote',
    component: NegatedEventFilterNote,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: {
        launched: false,
        config: {
            kind: NodeKind.ExperimentEventExposureConfig,
            event: '$pageview',
            properties: [
                {
                    type: PropertyFilterType.Event,
                    key: '$current_url',
                    operator: PropertyOperator.NotIContains,
                    value: '/internal',
                },
            ],
        },
    },
}
export default meta

export const BeforeLaunch: StoryObj<typeof NegatedEventFilterNote> = {}
