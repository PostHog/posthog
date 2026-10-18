import { useValues } from 'kea'
import { useState } from 'react'

import { LemonButton, LemonDialog, LemonSegmentedButton } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import type {
    PatchedSignalScoutConfigUpdateApi as SignalScoutConfigUpdate,
    SignalScoutConfigApi as SignalScoutConfig,
} from 'products/signals/frontend/generated/api.schemas'

import { captureScoutToolsPickerOpened, type ScoutSurface } from '../../../inboxAnalytics'
import { scoutDisplayName } from '../../../utils/scoutRunsWindow'
import { ScoutToolsPicker } from './ScoutToolsPicker'

type ScoutToolsMode = 'all' | 'list'

/**
 * Which MCP tools one scout may call: every tool, or a chosen list. "All tools" saves
 * `allowed_mcp_tools: null`. A list is picked and saved in {@link ScoutToolsPicker}, so choosing the
 * list mode only opens the picker.
 */
export function ScoutToolsSection({
    config,
    onUpdate,
    updating = false,
    surface,
}: {
    config: SignalScoutConfig
    onUpdate: (configId: string, updates: SignalScoutConfigUpdate) => void
    updating?: boolean
    surface: ScoutSurface
}): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const [pickerOpen, setPickerOpen] = useState(false)
    if (!featureFlags[FEATURE_FLAGS.SCOUTS_TOOL_ACCESS]) {
        return null
    }

    const savedTools = config.allowed_mcp_tools ?? null
    const mode: ScoutToolsMode = savedTools === null ? 'all' : 'list'
    const disabledReason = updating ? 'Saving scout settings' : undefined
    const openPicker = (): void => {
        captureScoutToolsPickerOpened({ skillName: config.skill_name, surface, hasToolList: savedTools !== null })
        setPickerOpen(true)
    }
    const confirmAllTools = (): void => {
        LemonDialog.open({
            title: 'Let this scout call every tool?',
            description:
                'The scout can call every tool its write access allows. Its current write access stays as it is.',
            primaryButton: {
                children: 'Allow all tools',
                onClick: () => onUpdate(config.id, { allowed_mcp_tools: null }),
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    return (
        <div className="flex flex-col gap-2 border-t border-primary pt-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex min-w-0 flex-col">
                    <span className="text-xs text-default">Tools</span>
                    <span className="text-[11.5px] text-muted">
                        {savedTools === null
                            ? 'This scout can call every tool.'
                            : `This scout can call ${savedTools.length} chosen ${savedTools.length === 1 ? 'tool' : 'tools'}.`}
                    </span>
                </div>
                <div className="flex items-center gap-2">
                    {savedTools !== null && (
                        <LemonButton
                            size="small"
                            type="secondary"
                            onClick={openPicker}
                            disabledReason={disabledReason}
                            data-attr="scout-tools-edit"
                        >
                            Edit tools
                        </LemonButton>
                    )}
                    <LemonSegmentedButton<ScoutToolsMode>
                        size="small"
                        value={mode}
                        disabledReason={disabledReason}
                        onChange={(next) => {
                            if (next === mode) {
                                return
                            }
                            if (next === 'list') {
                                openPicker()
                            } else {
                                confirmAllTools()
                            }
                        }}
                        options={[
                            { value: 'all', label: 'All tools', 'data-attr': 'scout-tools-mode-all' },
                            { value: 'list', label: 'Chosen tools', 'data-attr': 'scout-tools-mode-list' },
                        ]}
                    />
                </div>
            </div>
            {pickerOpen && (
                <ScoutToolsPicker
                    scoutName={scoutDisplayName(config)}
                    savedTools={savedTools}
                    onClose={() => setPickerOpen(false)}
                    onSave={(selection) => {
                        onUpdate(config.id, selection)
                        setPickerOpen(false)
                    }}
                />
            )}
        </div>
    )
}
