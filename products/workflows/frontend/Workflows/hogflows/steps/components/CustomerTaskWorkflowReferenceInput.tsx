import { useActions, useValues } from 'kea'
import { useEffect, useId, useState } from 'react'

import { LemonButton, LemonInputSelect, LemonLabel, LemonSegmentedButton } from '@posthog/lemon-ui'

import { MemberSelect } from 'lib/components/MemberSelect'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { CodeEditorInline } from 'lib/monaco/CodeEditorInline'
import { fullName } from 'lib/utils/strings'
import { membersLogic } from 'scenes/organization/membersLogic'

import { CyclotronJobInputSchemaType, CyclotronJobInputType, CyclotronJobInvocationGlobalsWithInputs } from '~/types'

import { customerTaskWorkflowAccountLogic } from './customerTaskWorkflowAccountLogic'

export function CustomerTaskWorkflowReferenceInput({
    schema,
    input,
    onChange,
    projectId,
    sampleGlobals,
    error,
}: {
    schema: CyclotronJobInputSchemaType
    input: CyclotronJobInputType
    onChange: (input: CyclotronJobInputType) => void
    projectId: number | null
    sampleGlobals: CyclotronJobInvocationGlobalsWithInputs
    error?: string
}): JSX.Element {
    const [mode, setMode] = useState<'raw' | 'picker'>('raw')
    const id = useId()
    const logic = customerTaskWorkflowAccountLogic({ id, projectId })
    const { choices, choicesLoading } = useValues(logic)
    const { loadChoices } = useActions(logic)
    const { members, meFirstMembers, membersLoading } = useValues(membersLogic)
    const { ensureAllMembersLoaded } = useActions(membersLogic)
    const isAccount = schema.key === 'account_id'
    const rawValue = input.value == null ? '' : String(input.value)
    const accountId = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(rawValue) ? rawValue : null
    const memberId = /^[1-9]\d*$/.test(rawValue) && Number(rawValue) <= 2147483647 ? Number(rawValue) : null
    // MemberSelect labels an id it cannot match with its defaultLabel, so a departed member or an
    // id from another organization would read as unassigned while the step still carries it.
    const savedMember = memberId === null ? null : (meFirstMembers.find((m) => m.user.id === memberId)?.user ?? null)

    useEffect(() => {
        if (mode === 'picker') {
            if (isAccount) {
                loadChoices({ query: '', accountId })
            } else {
                ensureAllMembersLoaded()
            }
        }
    }, [isAccount, mode, accountId, loadChoices, ensureAllMembersLoaded])

    return (
        <LemonField.Pure error={error} className="gap-1">
            <div
                className="flex items-center justify-between gap-2"
                data-attr={`customer-task-${schema.key}-input-mode`}
            >
                <LemonLabel showOptional>{isAccount ? 'Account' : 'Assignee'}</LemonLabel>
                <LemonSegmentedButton
                    size="xsmall"
                    value={mode}
                    onChange={setMode}
                    options={[
                        { value: 'raw' as const, label: 'Raw' },
                        { value: 'picker' as const, label: 'Picker' },
                    ]}
                />
            </div>
            {mode === 'raw' ? (
                <CodeEditorInline
                    className="ph-no-capture"
                    minHeight="37"
                    value={rawValue}
                    onChange={(value) => onChange({ ...input, value: value ?? '' })}
                    language={input.templating === 'liquid' ? 'liquid' : 'hogTemplate'}
                    globals={sampleGlobals}
                />
            ) : (
                <>
                    {isAccount ? (
                        choices?.failed ? (
                            <div className="flex items-center gap-2 text-danger">
                                <span>Could not load accounts.</span>
                                <LemonButton size="small" onClick={() => loadChoices({ query: '', accountId })}>
                                    Retry
                                </LemonButton>
                            </div>
                        ) : (
                            <LemonInputSelect
                                mode="single"
                                value={
                                    accountId && choices?.options.some((option) => option.key === accountId)
                                        ? [accountId]
                                        : []
                                }
                                options={choices?.options ?? []}
                                loading={choicesLoading || choices === null}
                                onInputChange={(query) => loadChoices({ query, accountId })}
                                onChange={(values) => onChange({ ...input, value: values[0] ?? '' })}
                                placeholder="No account"
                                disabledReason={projectId === null ? 'Select a project first' : undefined}
                                fullWidth
                                data-attr="workflow-customer-task-account"
                            />
                        )
                    ) : (
                        <MemberSelect
                            value={memberId}
                            defaultLabel="Unassigned"
                            type="secondary"
                            size="small"
                            onChange={(user) => onChange({ ...input, value: user ? String(user.id) : null })}
                        >
                            {() => (
                                <LemonButton type="secondary" size="small">
                                    {savedMember
                                        ? fullName(savedMember) || savedMember.email
                                        : memberId === null
                                          ? 'Unassigned'
                                          : `User ${memberId}`}
                                </LemonButton>
                            )}
                        </MemberSelect>
                    )}
                    {!isAccount && memberId !== null && !savedMember && members !== null && !membersLoading && (
                        <span className="text-xs text-secondary">
                            Saved assignee is unavailable. Choose another member or edit the raw value.
                        </span>
                    )}
                    {isAccount &&
                        accountId &&
                        choices &&
                        !choicesLoading &&
                        !choices.failed &&
                        !choices.options.some((option) => option.key === accountId) && (
                            <span className="text-xs text-secondary">
                                Saved account is unavailable. Choose another account or edit the raw value.
                            </span>
                        )}
                    {rawValue && !(isAccount ? accountId : memberId) && (
                        <span className="text-xs text-secondary">Choose a value to replace the raw expression.</span>
                    )}
                </>
            )}
        </LemonField.Pure>
    )
}
