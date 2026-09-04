import { useValues } from 'kea'
import { useState } from 'react'

import { LemonButton, LemonCollapse, LemonTag } from '@posthog/lemon-ui'

import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'

import type {
    PatchedSignalScoutConfigUpdateApi as SignalScoutConfigUpdate,
    SignalScoutConfigApi as SignalScoutConfig,
} from 'products/signals/frontend/generated/api.schemas'

import { scoutWriteAccessDisabledReason, scoutWriteScopeLabels } from './scoutWriteScopes'
import { ScoutWriteScopesPicker } from './ScoutWriteScopesPicker'

/**
 * Write access for one scout in its settings form: collapsed by default, with the scopes it holds
 * in the header so a read-only scout costs one line.
 *
 * The only control in this form that does not save on change. Widening what an unattended agent can
 * change in the project should take a deliberate save, not a stray click, so the switches stage a
 * draft and the save button commits it.
 */
export function ScoutWriteAccessSection({
    config,
    onUpdate,
    updating = false,
}: {
    config: SignalScoutConfig
    onUpdate: (configId: string, updates: SignalScoutConfigUpdate) => void
    updating?: boolean
}): JSX.Element {
    const { user } = useValues(userLogic)
    const { isAdminOrOwner } = useValues(organizationLogic)
    const saved = [...(config.write_scopes ?? [])]
    // Null until something is toggled, so the saved grant stays the truth — including after a
    // rejected save, which must leave the row where the server has it rather than where it was left.
    const [draft, setDraft] = useState<string[] | null>(null)
    const selected = draft ?? saved
    const changed = [...selected].sort().join() !== [...saved].sort().join()
    const heldLabels = scoutWriteScopeLabels(saved)
    const disabledReason =
        scoutWriteAccessDisabledReason(config, {
            isProjectAdmin: !!isAdminOrOwner,
            currentUserUuid: user?.uuid,
        }) ?? (updating ? 'Saving scout settings' : undefined)

    return (
        <div className="border-t border-primary pt-2">
            <LemonCollapse
                embedded
                size="small"
                panels={[
                    {
                        key: 'write-access',
                        dataAttr: 'scout-write-access',
                        header: (
                            <div className="flex flex-1 items-center justify-between gap-2">
                                <span className="text-xs text-default">Write access</span>
                                <div className="flex flex-wrap items-center gap-1">
                                    {heldLabels.length > 0 ? (
                                        heldLabels.map((label) => (
                                            <LemonTag key={label} size="small" type="option">
                                                {label}
                                            </LemonTag>
                                        ))
                                    ) : (
                                        <span className="text-[11.5px] text-muted">Read only</span>
                                    )}
                                </div>
                            </div>
                        ),
                        content: (
                            <div className="flex flex-col gap-2">
                                <ScoutWriteScopesPicker
                                    compact
                                    selectedScopes={selected}
                                    onChange={setDraft}
                                    disabledReason={disabledReason}
                                />
                                <div className="flex justify-end">
                                    <LemonButton
                                        size="small"
                                        type="secondary"
                                        loading={updating}
                                        disabledReason={disabledReason ?? (changed ? undefined : 'No changes to save')}
                                        onClick={() => {
                                            onUpdate(config.id, { write_scopes: selected })
                                            setDraft(null)
                                        }}
                                        data-attr="scout-write-access-save"
                                    >
                                        Save write access
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
