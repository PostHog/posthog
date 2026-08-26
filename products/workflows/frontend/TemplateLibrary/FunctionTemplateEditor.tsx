import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonButton, LemonInput, Spinner } from '@posthog/lemon-ui'

import { CyclotronJobInputs } from 'lib/components/CyclotronJob/CyclotronJobInputs'
import { templateToConfiguration } from 'scenes/hog-functions/configuration/hogFunctionConfigurationLogic'
import { HogFunctionIcon } from 'scenes/hog-functions/configuration/HogFunctionIcon'
import { hogFunctionTemplateListLogic } from 'scenes/hog-functions/list/hogFunctionTemplateListLogic'

import { CyclotronJobInputType, HogFunctionTemplateType } from '~/types'

import { messageTemplateLogic } from './messageTemplateLogic'

const destinationChooserFilter = (template: HogFunctionTemplateType): boolean =>
    template.type === 'destination' && !['hidden', 'coming_soon'].includes(template.status ?? '')

function DestinationChooser(): JSX.Element {
    const { setTemplateValue } = useActions(messageTemplateLogic)

    const listLogic = hogFunctionTemplateListLogic({
        type: 'destination',
        customFilterFunction: destinationChooserFilter,
    })
    const { loading, filteredTemplates, filters } = useValues(listLogic)
    const { loadHogFunctionTemplates, setFilters } = useActions(listLogic)

    useEffect(() => {
        loadHogFunctionTemplates()
    }, [loadHogFunctionTemplates])

    return (
        <div className="flex flex-col gap-1">
            <LemonInput
                type="search"
                placeholder="Search destinations"
                value={filters.search ?? ''}
                onChange={(search) => setFilters({ ...filters, search })}
            />
            {loading ? (
                <Spinner className="text-lg" />
            ) : (
                <ul className="flex flex-col gap-px max-h-120 overflow-y-auto">
                    {filteredTemplates.map((destination: HogFunctionTemplateType) => (
                        <li key={destination.id}>
                            <LemonButton
                                fullWidth
                                icon={<HogFunctionIcon src={destination.icon_url} size="small" />}
                                onClick={() => {
                                    setTemplateValue('content.function', {
                                        template_id: destination.id,
                                        inputs: templateToConfiguration(destination).inputs ?? {},
                                    })
                                }}
                            >
                                <div className="py-1">
                                    <div>{destination.name}</div>
                                    <div className="text-xs text-muted">{destination.description}</div>
                                </div>
                            </LemonButton>
                        </li>
                    ))}
                </ul>
            )}
        </div>
    )
}

export function FunctionTemplateEditor(): JSX.Element {
    const { template, hogFunctionTemplate, hogFunctionTemplateLoading } = useValues(messageTemplateLogic)
    const { setTemplateValue } = useActions(messageTemplateLogic)

    const functionContent = template.content.function
    if (!functionContent?.template_id) {
        return <DestinationChooser />
    }

    if (hogFunctionTemplateLoading || !hogFunctionTemplate) {
        return <Spinner className="text-lg" />
    }

    // Secret inputs are never stored in the library, so don't offer them here
    const visibleInputsSchema = (hogFunctionTemplate.inputs_schema ?? []).filter((schema) => !schema.secret)
    const hasSecretInputs = (hogFunctionTemplate.inputs_schema ?? []).some((schema) => schema.secret)

    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2">
                <HogFunctionIcon src={hogFunctionTemplate.icon_url} size="small" />
                <span className="font-semibold flex-1">{hogFunctionTemplate.name}</span>
                <LemonButton
                    size="small"
                    type="secondary"
                    onClick={() => setTemplateValue('content.function', { template_id: '', inputs: {} })}
                >
                    Change destination
                </LemonButton>
            </div>
            <CyclotronJobInputs
                configuration={{
                    inputs: (functionContent.inputs ?? {}) as Record<string, CyclotronJobInputType>,
                    inputs_schema: visibleInputsSchema,
                }}
                showSource={false}
                sampleGlobalsWithInputs={null}
                onInputChange={(key, value) =>
                    setTemplateValue('content.function.inputs', { ...functionContent.inputs, [key]: value })
                }
            />
            {hasSecretInputs && (
                <p className="text-xs text-secondary mb-0">
                    Secret fields are not stored in the library. You enter them in each workflow step that uses this
                    template.
                </p>
            )}
        </div>
    )
}
