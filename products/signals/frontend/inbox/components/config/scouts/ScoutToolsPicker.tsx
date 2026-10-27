import { useMountedLogic, useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCheck } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonInput, LemonModal, LemonTag, Spinner } from '@posthog/lemon-ui'

import type { ScoutToolCatalogueApi, ToolPresetEnumApi } from 'products/signals/frontend/generated/api.schemas'

import { scoutToolCatalogueLogic } from '../../../logics/scoutToolCatalogueLogic'
import {
    deriveScoutToolWriteScopes,
    groupScoutTools,
    runContextScoutToolLabels,
    scoutToolUnavailableReason,
    selectableScoutTools,
} from './scoutTools'
import { scoutWriteScopeLabels } from './scoutWriteScopes'

/** What a save sends. Never `write_scopes`: the API derives those from the list. */
export type ScoutToolsSelection = { allowed_mcp_tools: string[] } | { tool_preset: ToolPresetEnumApi }

interface ScoutToolsPickerProps {
    scoutName: string
    /** The saved list, or null when the scout may call every tool. */
    savedTools: readonly string[] | null
    onSave: (selection: ScoutToolsSelection) => void
    onClose: () => void
}

/**
 * Picks the MCP tools one scout may call. The draft stays here until the save button, because a
 * list with write tools widens what an unattended agent can change in the project.
 */
export function ScoutToolsPicker({ scoutName, savedTools, onSave, onClose }: ScoutToolsPickerProps): JSX.Element {
    useMountedLogic(scoutToolCatalogueLogic)
    const { catalogue, catalogueLoading, catalogueFailed } = useValues(scoutToolCatalogueLogic)
    const { loadCatalogue } = useActions(scoutToolCatalogueLogic)
    const [selected, setSelected] = useState<string[]>([...(savedTools ?? [])])
    const selectedTools = catalogue ? selected.filter((tool) => !catalogue.run_context_tools.includes(tool)) : selected
    // Set only while the draft is exactly a preset someone picked, so the save names the preset.
    const [preset, setPreset] = useState<ToolPresetEnumApi | null>(null)
    const edited = preset !== null || [...selectedTools].sort().join() !== [...(savedTools ?? [])].sort().join()
    // Moving from all tools to a list is a change even when the list is still empty.
    const changed = edited || savedTools === null

    let body: JSX.Element
    if (catalogue) {
        body = (
            <ToolCatalogueBody
                catalogue={catalogue}
                selected={selectedTools}
                preset={preset}
                onChange={(tools, nextPreset = null) => {
                    setSelected(tools)
                    setPreset(nextPreset)
                }}
            />
        )
    } else if (catalogueFailed) {
        body = (
            <div className="flex flex-col items-start gap-2 rounded border border-dashed px-3 py-3">
                <span className="text-sm">
                    Couldn't load the tool list. Try again, or close this and come back later.
                </span>
                <LemonButton size="small" type="secondary" onClick={loadCatalogue} loading={catalogueLoading}>
                    Try again
                </LemonButton>
            </div>
        )
    } else {
        body = (
            <div className="flex items-center gap-2 rounded border border-dashed px-3 py-4 text-sm text-secondary">
                <Spinner /> Loading tools...
            </div>
        )
    }

    return (
        <LemonModal
            isOpen
            onClose={onClose}
            title={`Tools for ${scoutName}`}
            description="Choose the tools this scout can call. It can't call any other tool."
            width={640}
            hasUnsavedInput={edited}
            footer={
                <>
                    <LemonButton type="secondary" onClick={onClose}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        disabledReason={!catalogue ? 'Loading tools' : !changed ? 'No changes to save' : undefined}
                        onClick={() => {
                            onSave(preset ? { tool_preset: preset } : { allowed_mcp_tools: [...selectedTools].sort() })
                        }}
                        data-attr="scout-tools-save"
                    >
                        Save tools
                    </LemonButton>
                </>
            }
        >
            {body}
        </LemonModal>
    )
}

function ToolCatalogueBody({
    catalogue,
    selected,
    preset,
    onChange,
}: {
    catalogue: ScoutToolCatalogueApi
    selected: string[]
    preset: ToolPresetEnumApi | null
    onChange: (tools: string[], preset?: ToolPresetEnumApi | null) => void
}): JSX.Element {
    const [search, setSearch] = useState('')
    const groups = groupScoutTools(catalogue, search)
    const selectable = new Set(selectableScoutTools(catalogue).map((tool) => tool.name))
    const alwaysHeld = runContextScoutToolLabels(catalogue)
    const writeScopes = deriveScoutToolWriteScopes(catalogue, selected)
    const toggle = (name: string, checked: boolean): void => {
        onChange(checked ? [...selected, name] : selected.filter((tool) => tool !== name))
    }

    return (
        <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs text-secondary">Start from</span>
                {catalogue.tool_presets.map((option) => (
                    <LemonButton
                        key={option.name}
                        size="xsmall"
                        type="secondary"
                        active={preset === option.name}
                        onClick={() =>
                            onChange(
                                option.tools.filter((tool) => selectable.has(tool)),
                                option.name as ToolPresetEnumApi
                            )
                        }
                        data-attr={`scout-tools-preset-${option.name}`}
                    >
                        {option.label}
                    </LemonButton>
                ))}
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    disabledReason={selected.length === 0 ? 'No tools chosen' : undefined}
                    onClick={() => onChange([])}
                >
                    Clear
                </LemonButton>
            </div>
            <LemonInput
                type="search"
                size="small"
                placeholder="Search tools"
                value={search}
                onChange={setSearch}
                fullWidth
                autoFocus
            />
            <div className="flex max-h-[50vh] flex-col gap-3 overflow-y-auto pr-1">
                {groups.length === 0 ? (
                    <span className="text-sm text-secondary">No tools match "{search}". Try another search.</span>
                ) : (
                    groups.map((group) => (
                        <div key={group.category} className="flex flex-col gap-1">
                            <div className="flex items-baseline justify-between gap-2">
                                <span className="text-[11px] font-medium uppercase tracking-wide text-muted">
                                    {group.category}
                                </span>
                                <span className="shrink-0 text-[11px] text-muted">
                                    {group.tools.filter((tool) => selected.includes(tool.name)).length} of{' '}
                                    {group.tools.length}
                                </span>
                            </div>
                            {group.tools.map((tool) => (
                                <div key={tool.name} className="flex items-start justify-between gap-2">
                                    <LemonCheckbox
                                        className="min-w-0"
                                        checked={selected.includes(tool.name)}
                                        onChange={(checked) => toggle(tool.name, checked)}
                                        disabledReason={scoutToolUnavailableReason(tool)}
                                        label={
                                            <span className="flex min-w-0 flex-col">
                                                <span className="text-sm">{tool.title}</span>
                                                <span className="line-clamp-2 text-xs text-secondary">
                                                    {tool.summary}
                                                </span>
                                            </span>
                                        }
                                    />
                                    <LemonTag size="small" type={tool.is_read_only ? 'muted' : 'warning'}>
                                        {tool.is_read_only ? 'Read' : 'Write'}
                                    </LemonTag>
                                </div>
                            ))}
                        </div>
                    ))
                )}
                <div className="flex flex-col gap-1">
                    <span className="text-[11px] font-medium uppercase tracking-wide text-muted">Always available</span>
                    <span className="text-xs text-secondary">
                        Every scout run can use these to load skills, report findings, and keep its memory.
                    </span>
                    <div className="flex flex-wrap gap-1">
                        {alwaysHeld.map((label) => (
                            <LemonTag key={label} size="small" type="muted" icon={<IconCheck />}>
                                {label}
                            </LemonTag>
                        ))}
                    </div>
                </div>
            </div>
            <div className="flex flex-col gap-1 rounded border border-primary bg-surface-secondary px-3 py-2">
                <span className="text-xs font-medium">Write access from this list</span>
                {writeScopes.length === 0 ? (
                    <span className="text-xs text-secondary">
                        Read only. The scout can still write notebooks, its findings, and its memory.
                    </span>
                ) : (
                    <>
                        <div className="flex flex-wrap gap-1">
                            {writeScopes
                                .map((scope) => scoutWriteScopeLabels([scope])[0] ?? scope)
                                .map((label) => (
                                    <LemonTag key={label} size="small" type="option">
                                        {label}
                                    </LemonTag>
                                ))}
                        </div>
                        <span className="text-xs text-secondary">
                            Each one covers every object of its kind in the project, not only the ones the scout makes.
                        </span>
                    </>
                )}
            </div>
        </div>
    )
}
