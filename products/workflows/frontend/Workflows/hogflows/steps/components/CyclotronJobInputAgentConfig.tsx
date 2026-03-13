import { useValues } from 'kea'
import { useCallback, useRef, useState } from 'react'

import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonCollapse, LemonInput, LemonLabel, LemonSelect, LemonTextArea } from '@posthog/lemon-ui'

import type { CustomInputRendererProps } from 'lib/components/CyclotronJob/customInputRenderers'
import { IntegrationChoice } from 'lib/components/CyclotronJob/integrations/IntegrationChoice'
import { GitHubRepositoryPicker } from 'lib/integrations/GitHubIntegrationHelpers'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'

interface AgentConfigValue {
    prompt: string
    github_installation: number | null
    repository: string | null
    output_schema: Record<string, unknown> | null
}

const DEFAULTS: AgentConfigValue = {
    prompt: '',
    github_installation: null,
    repository: null,
    output_schema: null,
}

interface OutputField {
    key: string
    type: 'string' | 'number'
}

const TYPE_OPTIONS = [
    { value: 'string' as const, label: 'String' },
    { value: 'number' as const, label: 'Number' },
]

function fieldsToSchema(fields: OutputField[]): Record<string, unknown> | null {
    const valid = fields.filter((f) => f.key.trim())
    if (valid.length === 0) {
        return null
    }
    return {
        type: 'object',
        properties: Object.fromEntries(valid.map((f) => [f.key, { type: f.type }])),
        required: valid.map((f) => f.key),
    }
}

function schemaToFields(schema: Record<string, unknown> | null): OutputField[] {
    if (!schema || typeof schema !== 'object') {
        return []
    }
    const properties = schema.properties as Record<string, { type?: string }> | undefined
    if (!properties || typeof properties !== 'object') {
        return []
    }
    return Object.entries(properties).map(([key, prop]) => ({
        key,
        type: prop?.type === 'number' ? ('number' as const) : ('string' as const),
    }))
}

export default function CyclotronJobInputAgentConfig({ value, onChange }: CustomInputRendererProps): JSX.Element {
    const config: AgentConfigValue = { ...DEFAULTS, ...value }
    const { integrations } = useValues(integrationsLogic)

    const update = useCallback(
        (patch: Partial<AgentConfigValue>) => {
            onChange({ ...config, ...patch })
        },
        // eslint-disable-next-line react-hooks/exhaustive-deps
        [onChange, JSON.stringify(config)]
    )

    const integration = integrations?.find((i) => i.id === config.github_installation)

    // Local state for output fields so empty rows can exist while the user types
    const [outputFields, setOutputFields] = useState<OutputField[]>(() => schemaToFields(config.output_schema))
    // Track the last schema we synced from to avoid resetting local state on our own updates
    const lastSyncedSchema = useRef(config.output_schema)
    if (config.output_schema !== lastSyncedSchema.current) {
        // External change (e.g. undo) — resync local state
        const incomingStr = JSON.stringify(config.output_schema)
        const currentStr = JSON.stringify(lastSyncedSchema.current)
        if (incomingStr !== currentStr) {
            const newFields = schemaToFields(config.output_schema)
            setOutputFields(newFields)
            lastSyncedSchema.current = config.output_schema
        }
    }

    const updateFields = useCallback(
        (fields: OutputField[]) => {
            setOutputFields(fields)
            const schema = fieldsToSchema(fields)
            lastSyncedSchema.current = schema
            update({ output_schema: schema })
        },
        [update]
    )

    return (
        <div className="space-y-3">
            {/* Prompt */}
            <div>
                <LemonLabel>Prompt</LemonLabel>
                <LemonTextArea
                    value={config.prompt ?? ''}
                    onChange={(val) => update({ prompt: val })}
                    placeholder="Describe what the agent should do..."
                    minRows={3}
                    maxRows={12}
                    className="ph-no-capture"
                />
                <p className="text-xs text-secondary mt-1">
                    Use <code className="text-xs">{'{variables.xxx}'}</code> to reference values from previous steps.
                </p>
            </div>

            {/* Optional sections */}
            <LemonCollapse
                multiple
                embedded
                size="small"
                panels={[
                    {
                        key: 'repository',
                        header: (
                            <span className="font-semibold text-xs">
                                Repository{' '}
                                {integration ? (
                                    <span className="font-normal text-secondary">
                                        — {config.repository ?? 'not selected'}
                                    </span>
                                ) : (
                                    <span className="font-normal text-secondary">— optional</span>
                                )}
                            </span>
                        ),
                        content: (
                            <div className="space-y-2 pt-1">
                                <div>
                                    <LemonLabel className="text-xs">GitHub connection</LemonLabel>
                                    <IntegrationChoice
                                        integration="github"
                                        value={config.github_installation ?? undefined}
                                        onChange={(val) => {
                                            update({
                                                github_installation: val,
                                                ...(val !== config.github_installation ? { repository: null } : {}),
                                            })
                                        }}
                                    />
                                </div>
                                {config.github_installation ? (
                                    <div>
                                        <LemonLabel className="text-xs">Repository</LemonLabel>
                                        <GitHubRepositoryPicker
                                            value={config.repository ?? ''}
                                            onChange={(val) => update({ repository: val })}
                                            integrationId={config.github_installation}
                                        />
                                    </div>
                                ) : null}
                            </div>
                        ),
                    },
                    {
                        key: 'output_schema',
                        header: (
                            <span className="font-semibold text-xs">
                                Structured output{' '}
                                {outputFields.length > 0 ? (
                                    <span className="font-normal text-secondary">
                                        — {outputFields.length} field{outputFields.length !== 1 ? 's' : ''}
                                    </span>
                                ) : (
                                    <span className="font-normal text-secondary">— optional</span>
                                )}
                            </span>
                        ),
                        content: (
                            <div className="pt-1">
                                <p className="text-xs text-secondary mb-2">
                                    Define the fields the agent should return. When provided, the agent will use the{' '}
                                    <code className="text-xs">submit_result</code> tool to return structured data.
                                </p>
                                <div className="space-y-1.5">
                                    {outputFields.map((field, index) => (
                                        <div key={index} className="flex items-center gap-1.5">
                                            <LemonInput
                                                size="small"
                                                value={field.key}
                                                onChange={(val) => {
                                                    const next = [...outputFields]
                                                    next[index] = { ...field, key: val }
                                                    updateFields(next)
                                                }}
                                                placeholder="Field name"
                                                className="flex-1"
                                            />
                                            <LemonSelect
                                                size="small"
                                                value={field.type}
                                                onChange={(val) => {
                                                    const next = [...outputFields]
                                                    next[index] = { ...field, type: val }
                                                    updateFields(next)
                                                }}
                                                options={TYPE_OPTIONS}
                                            />
                                            <LemonButton
                                                size="small"
                                                icon={<IconTrash />}
                                                status="danger"
                                                noPadding
                                                onClick={() => {
                                                    const next = outputFields.filter((_, i) => i !== index)
                                                    updateFields(next)
                                                }}
                                            />
                                        </div>
                                    ))}
                                    <LemonButton
                                        size="small"
                                        type="secondary"
                                        icon={<IconPlus />}
                                        onClick={() => updateFields([...outputFields, { key: '', type: 'string' }])}
                                    >
                                        Add field
                                    </LemonButton>
                                </div>
                            </div>
                        ),
                    },
                ]}
            />
        </div>
    )
}
