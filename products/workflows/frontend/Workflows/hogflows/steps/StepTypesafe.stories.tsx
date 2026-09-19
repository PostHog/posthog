import type { Meta, StoryFn } from '@storybook/react'
import { BindLogic } from 'kea'
import { useState } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'
import { CyclotronJobInputType } from '~/types'

import { workflowLogic } from '../../workflowLogic'
import { HogFlowFunctionConfiguration } from './components/HogFlowFunctionConfiguration'
import template from './typesafe-template.json'

const meta: Meta = {
    title: 'Products/Workflows/Steps/TypeSafe',
    parameters: {
        featureFlags: [FEATURE_FLAGS.TYPESAFE_WORKFLOW],
        testOptions: { waitForSelector: '.monaco-editor' },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/hog_function_templates': { count: 1, results: [template] },
            },
        }),
    ],
}
export default meta

const Template: StoryFn<{ narrow?: boolean }> = ({ narrow }) => {
    const [inputs, setInputs] = useState<Record<string, CyclotronJobInputType>>({
        api_key: { value: '', secret: true },
        question: { value: 'Which activity does the text describe?' },
        context: { value: { text: '{event.properties.text}' }, templating: 'hog' },
        categories: {
            value: { painting: 'Painting a picture', gardening: 'Growing plants', other: 'Any other activity' },
        },
    })

    return (
        <BindLogic logic={workflowLogic} props={{ id: 'new' }}>
            <div className={`${narrow ? 'w-[520px]' : 'w-[800px]'} p-4 flex flex-col gap-4`}>
                <HogFlowFunctionConfiguration templateId={template.id} inputs={inputs} setInputs={setInputs} />
            </div>
        </BindLogic>
    )
}

export const Configuration = Template.bind({})
export const Narrow = Template.bind({})
Narrow.args = { narrow: true }
