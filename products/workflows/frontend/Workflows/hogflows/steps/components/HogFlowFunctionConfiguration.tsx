import { useValues } from 'kea'
import { useEffect } from 'react'

import { Spinner } from '@posthog/lemon-ui'

import { CyclotronJobInputs } from 'lib/components/CyclotronJob/CyclotronJobInputs'
import { templateToConfiguration } from 'scenes/hog-functions/configuration/hogFunctionConfigurationLogic'

import { CyclotronJobInputType } from '~/types'

import { campaignLogic } from '../../../campaignLogic'

export function HogFlowFunctionConfiguration({
    templateId,
    inputs,
    setInputs,
    errors,
}: {
    templateId: string
    inputs: Record<string, CyclotronJobInputType>
    setInputs: (inputs: Record<string, CyclotronJobInputType>) => void
    errors?: Record<string, string>
}): JSX.Element {
    const { hogFunctionTemplatesById, hogFunctionTemplatesByIdLoading } = useValues(campaignLogic)

    const template = hogFunctionTemplatesById[templateId]
    useEffect(() => {
        if (template && Object.keys(inputs ?? {}).length === 0) {
            setInputs(templateToConfiguration(template).inputs ?? {})
        }
    }, [template, setInputs, inputs])

    if (hogFunctionTemplatesByIdLoading) {
        return (
            <div className="flex justify-center items-center">
                <Spinner />
            </div>
        )
    }

    if (!template) {
        return <div>Template not found!</div>
    }

    return (
        <CyclotronJobInputs
            errors={errors}
            configuration={{
                inputs: inputs as Record<string, CyclotronJobInputType>,
                inputs_schema: template?.inputs_schema ?? [],
            }}
            showSource={false}
            sampleGlobalsWithInputs={null} // TODO: Load this based on the trigger event
            onInputChange={(key, value) => setInputs({ ...inputs, [key]: value })}
        />
    )
}
