import { Meta, StoryFn } from '@storybook/react'
import { useState } from 'react'

import { UtmTagFields, UtmTagValues } from './UtmTagFields'

const meta: Meta<typeof UtmTagFields> = {
    title: 'Products/Workflows/Steps/UTM tag fields',
    component: UtmTagFields,
}
export default meta

const Template: StoryFn<{ initial: UtmTagValues }> = ({ initial }) => {
    const [value, setValue] = useState<UtmTagValues>(initial)
    return (
        <div className="w-120">
            <UtmTagFields value={value} onChange={setValue} campaignDefault="Spring sale" contentDefault="Send email" />
        </div>
    )
}

export const CustomValues = Template.bind({})
CustomValues.args = { initial: { utm_source: 'newsletter', utm_campaign: '{{ person.properties.plan }}' } }
