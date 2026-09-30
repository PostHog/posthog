import { useEffect, useState } from 'react'

import { LemonButton, LemonCollapse, LemonTag, LemonTextArea } from '@posthog/lemon-ui'

import { objectsEqual } from 'lib/utils/objects'

import type {
    PatchedSignalScoutConfigUpdateApi as SignalScoutConfigUpdate,
    SignalScoutConfigApi as SignalScoutConfig,
} from 'products/signals/frontend/generated/api.schemas'

import { parseScoutStructuredOutputSchema, scoutStructuredOutputFieldNames } from './scoutStructuredOutput'

const HEADER_FIELD_LIMIT = 3

const SCHEMA_PLACEHOLDER = `{
  "type": "object",
  "properties": {
    "verdict": { "enum": ["good", "bad", "unsure"] },
    "reason": { "type": "string" }
  },
  "required": ["verdict", "reason"]
}`

/**
 * The record schema for one scout in its settings form: collapsed by default, with the record's
 * field names in the header so a scout that records nothing costs one line.
 *
 * Like write access, this does not save on change. The scout reads the schema verbatim in its run
 * prompt, and a half-typed schema would rewrite what the next run is asked to produce, so the
 * editor stages a draft and the save button commits it.
 *
 * The editor stays live for everyone. Only a person who may edit skills can set a schema, and the
 * client cannot resolve that, so the API refuses and its message names what is missing.
 */
export function ScoutStructuredOutputSection({
    config,
    onUpdate,
    updating = false,
}: {
    config: SignalScoutConfig
    onUpdate: (configId: string, updates: SignalScoutConfigUpdate) => void
    updating?: boolean
}): JSX.Element {
    const saved = config.structured_output_schema ?? null
    const savedText = saved ? JSON.stringify(saved, null, 2) : ''
    // Null until something is typed, so an untouched editor follows the saved schema.
    const [draft, setDraft] = useState<string | null>(null)
    // The schema the last save sent, held until the request settles. The draft clears only if the
    // stored schema then matches it. A rejected save reverts the config, so the typed JSON stays on
    // screen to correct and save again.
    const [submitted, setSubmitted] = useState<Record<string, unknown> | null>(null)
    const [confirmingTurnOff, setConfirmingTurnOff] = useState(false)
    useEffect(() => {
        if (updating || !submitted) {
            return
        }
        if (objectsEqual(saved, submitted)) {
            setDraft(null)
        }
        setSubmitted(null)
    }, [updating, submitted, saved])
    const text = draft ?? savedText
    const { schema, error } = parseScoutStructuredOutputSchema(text)
    const changed = JSON.stringify(schema) !== JSON.stringify(saved)
    const fieldNames = scoutStructuredOutputFieldNames(saved)
    const headerFields = fieldNames.slice(0, HEADER_FIELD_LIMIT)
    const tagType = config.emit ? 'option' : 'muted'
    const disabledReason = updating ? 'Saving scout settings' : undefined
    const saveDisabledReason =
        disabledReason ??
        error ??
        (schema && changed ? undefined : !schema && saved ? 'To remove the schema, use Turn off' : 'No changes to save')

    return (
        <div className="border-t border-primary pt-2">
            <LemonCollapse
                embedded
                size="small"
                panels={[
                    {
                        key: 'structured-output',
                        dataAttr: 'scout-structured-output',
                        header: (
                            <div className="flex flex-1 items-center justify-between gap-2">
                                <span className="text-xs text-default">Structured output</span>
                                <div className="flex flex-wrap items-center gap-1">
                                    {saved ? (
                                        <>
                                            {headerFields.map((name) => (
                                                <LemonTag key={name} size="small" type={tagType}>
                                                    {name}
                                                </LemonTag>
                                            ))}
                                            {fieldNames.length > headerFields.length ? (
                                                <LemonTag size="small" type={tagType}>
                                                    {`+${fieldNames.length - headerFields.length}`}
                                                </LemonTag>
                                            ) : null}
                                            {fieldNames.length === 0 ? (
                                                <LemonTag size="small" type={tagType}>
                                                    Schema set
                                                </LemonTag>
                                            ) : null}
                                            {!config.emit && (
                                                <span className="text-[11.5px] text-muted">
                                                    Inactive during dry run
                                                </span>
                                            )}
                                        </>
                                    ) : (
                                        <span className="text-[11.5px] text-muted">Off</span>
                                    )}
                                </div>
                            </div>
                        ),
                        content: (
                            <div className="flex flex-col gap-2">
                                <span className="text-[11.5px] text-muted">
                                    A JSON Schema for one record this scout measures, such as a verdict and a reason.
                                    The scout sees it in its prompt, and every record it submits is checked against it
                                    and saved as a $scout_structured_output event you can chart. Only a person who can
                                    edit skills may set a schema.
                                </span>
                                <LemonTextArea
                                    value={text}
                                    placeholder={SCHEMA_PLACEHOLDER}
                                    minRows={6}
                                    maxRows={16}
                                    className="font-mono text-[11.5px]"
                                    disabled={updating}
                                    onChange={setDraft}
                                    aria-label={`${config.skill_name} record schema`}
                                />
                                {error ? <span className="text-[11.5px] text-danger">{error}</span> : null}
                                {!config.emit ? (
                                    <span className="text-[11.5px] text-warning">
                                        This scout is in a dry run, so it records nothing. Turn on "Write signals to the
                                        inbox" to use the schema.
                                    </span>
                                ) : null}
                                <div className="flex flex-wrap items-center justify-end gap-2">
                                    {confirmingTurnOff ? (
                                        <>
                                            <span className="mr-auto min-w-0 text-[11.5px] text-default">
                                                Turn off structured output?
                                            </span>
                                            <div className="flex shrink-0 gap-2">
                                                <LemonButton
                                                    size="small"
                                                    type="secondary"
                                                    onClick={() => setConfirmingTurnOff(false)}
                                                >
                                                    Cancel
                                                </LemonButton>
                                                <LemonButton
                                                    size="small"
                                                    type="primary"
                                                    status="danger"
                                                    loading={updating}
                                                    disabledReason={disabledReason}
                                                    onClick={() => {
                                                        onUpdate(config.id, { structured_output_schema: null })
                                                        setDraft(null)
                                                        setConfirmingTurnOff(false)
                                                    }}
                                                    data-attr="scout-structured-output-clear"
                                                >
                                                    Turn off
                                                </LemonButton>
                                            </div>
                                        </>
                                    ) : (
                                        <>
                                            {saved ? (
                                                <LemonButton
                                                    size="small"
                                                    type="secondary"
                                                    status="danger"
                                                    className="mr-auto"
                                                    disabledReason={disabledReason}
                                                    onClick={() => setConfirmingTurnOff(true)}
                                                >
                                                    Turn off
                                                </LemonButton>
                                            ) : null}
                                            {draft !== null && changed ? (
                                                <LemonButton
                                                    size="small"
                                                    type="tertiary"
                                                    disabledReason={disabledReason}
                                                    onClick={() => setDraft(null)}
                                                    data-attr="scout-structured-output-discard"
                                                >
                                                    Discard
                                                </LemonButton>
                                            ) : null}
                                            <LemonButton
                                                size="small"
                                                type="secondary"
                                                loading={updating}
                                                disabledReason={saveDisabledReason}
                                                onClick={() => {
                                                    if (!schema) {
                                                        return
                                                    }
                                                    onUpdate(config.id, { structured_output_schema: schema })
                                                    setSubmitted(schema)
                                                }}
                                                data-attr="scout-structured-output-save"
                                            >
                                                Save schema
                                            </LemonButton>
                                        </>
                                    )}
                                </div>
                            </div>
                        ),
                    },
                ]}
            />
        </div>
    )
}
