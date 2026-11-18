import { Meta, StoryFn } from '@storybook/react'
import { useState } from 'react'

import { useAvailableFeatures } from '~/mocks/features'
import { AvailableFeature } from '~/types'

import { LogsRetentionPeriodPicker, LogsRetentionPeriodPickerProps } from './LogsRetentionPeriodPicker'

type StoryProps = Pick<LogsRetentionPeriodPickerProps, 'value' | 'allowCustom' | 'customCommit'> & {
    features?: AvailableFeature[]
}

const meta: Meta<StoryProps> = {
    title: 'Logs/LogsRetentionPeriodPicker',
    parameters: {
        layout: 'padded',
        viewMode: 'story',
        testOptions: { waitForLoadersToDisappear: false },
    },
}
export default meta

const Template: StoryFn<StoryProps> = (args) => {
    useAvailableFeatures(args.features ?? [AvailableFeature.LOGS_RETENTION_30D])
    const [value, setValue] = useState(args.value)
    return (
        <div className="max-w-2xl">
            <LogsRetentionPeriodPicker
                value={value}
                onChange={setValue}
                allowCustom={args.allowCustom}
                customCommit={args.customCommit}
            />
            <p className="text-secondary text-sm mt-2 mb-0">Selected: {value} days</p>
        </div>
    )
}

export const BaseTiers = Template.bind({})
BaseTiers.args = { value: 14, allowCustom: false, customCommit: 'apply' }

export const Presets = Template.bind({})
Presets.args = { value: 360, allowCustom: true, customCommit: 'apply' }

export const CustomMonthsWithApply = Template.bind({})
CustomMonthsWithApply.args = { value: 180, allowCustom: true, customCommit: 'apply' }

export const CustomMonthsInForm = Template.bind({})
CustomMonthsInForm.args = { value: 180, allowCustom: true, customCommit: 'change' }

export const StoredCustomMonthsWithoutFlag = Template.bind({})
StoredCustomMonthsWithoutFlag.args = { value: 180, allowCustom: false, customCommit: 'apply' }

export const StoredCustomMonthsWithoutPaidRetention = Template.bind({})
StoredCustomMonthsWithoutPaidRetention.args = { value: 180, allowCustom: true, customCommit: 'apply', features: [] }
