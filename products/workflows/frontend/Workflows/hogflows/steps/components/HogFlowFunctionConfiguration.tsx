import { useValues } from 'kea'
import { useEffect } from 'react'

import { Spinner } from '@posthog/lemon-ui'

import { CyclotronJobInputs } from 'lib/components/CyclotronJob/CyclotronJobInputs'
import { templateToConfiguration } from 'scenes/hog-functions/configuration/hogFunctionConfigurationLogic'

import { CyclotronJobInputType, HogFunctionMappingType } from '~/types'

import { workflowLogic } from '../../../workflowLogic'
import { buildSampleGlobals } from '../../registry/triggers/sampleGlobals'
import { HogFlowFunctionMappings } from './HogFlowFunctionMappings'

export function HogFlowFunctionConfiguration({
    templateId,
    inputs,
    setInputs,
    mappings,
    setMappings,
    errors,
}: {
    templateId: string
    inputs: Record<string, CyclotronJobInputType>
    mappings?: HogFunctionMappingType[]
    setInputs: (inputs: Record<string, CyclotronJobInputType>) => void
    setMappings?: (mappings: HogFunctionMappingType[]) => void
    errors?: Record<string, string>
}): JSX.Element {
    const { workflow, hogFunctionTemplatesById, hogFunctionTemplatesByIdLoading } = useValues(workflowLogic)

    const template = hogFunctionTemplatesById[templateId]

    useEffect(() => {
        // oxlint-disable-next-line exhaustive-deps
        if (template && Object.keys(inputs ?? {}).length === 0) {
            setInputs(templateToConfiguration(template).inputs ?? {})
        }
    }, [templateId])

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

    const sampleGlobals = buildSampleGlobals(workflow)

    return (
        <>
            <CyclotronJobInputs
                errors={errors}
                configuration={{
                    inputs: inputs as Record<string, CyclotronJobInputType>,
                    inputs_schema: template?.inputs_schema ?? [],
                }}
                showSource={false}
                sampleGlobalsWithInputs={sampleGlobals}
                onInputChange={(key, value) => setInputs({ ...inputs, [key]: value })}
            />
            <HogFlowFunctionMappings
                useMapping={Array.isArray(mappings) ?? (template?.mapping_templates?.length ?? 0) > 0}
                inputs={inputs}
                inputs_schema={template?.inputs_schema ?? []}
                mappings={mappings ?? []}
                mappingTemplates={template?.mapping_templates ?? []}
                onChange={(mappings) => setMappings?.(mappings)}
            />
        </>
    )
}
