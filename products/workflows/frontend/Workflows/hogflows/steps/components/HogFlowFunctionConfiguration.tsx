import { useValues } from 'kea'
import { useEffect } from 'react'

import { Spinner } from '@posthog/lemon-ui'

import { CyclotronJobInputs } from 'lib/components/CyclotronJob/CyclotronJobInputs'
import { templateToConfiguration } from 'scenes/hog-functions/configuration/hogFunctionConfigurationLogic'

import { CyclotronJobInputType } from '~/types'

import { workflowLogic } from '../../../workflowLogic'

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

    const triggerType = workflow?.trigger?.type

    let sampleGlobals = {}

    if (triggerType === 'webhook') {
        sampleGlobals = {
            request: {
                method: 'POST',
                headers: {
                    'content-type': 'application/json',
                    'user-agent': 'PostHog-Webhook/1.0',
                },
                body: {
                    example_key: 'example_value',
                },
                url: 'https://your-app.com/webhook',
            },
        }
    } else if (triggerType === 'manual') {
        sampleGlobals = {}
    } else {
        // Event-based triggers
        sampleGlobals = {
            event: {
                event: 'example_event',
                distinct_id: 'user123',
                properties: {
                    $current_url: 'https://example.com',
                    custom_property: 'value',
                },
                timestamp: '2024-01-01T12:00:00Z',
            },
            person: {
                id: 'person123',
                properties: {
                    email: 'user@example.com',
                    name: 'John Doe',
                },
            },
            groups: {},
        }
    }

    return (
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
    )
}
