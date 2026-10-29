import { type ReactElement, useMemo } from 'react'
import { Gesture } from 'react-native-gesture-handler'

import type {
    ModelChoiceApi,
    PermissionModeApi,
    ReasoningEffortApi,
    ResolvedAiRunDefaultsApi,
    RuntimeAdapterApi,
} from '@/api/tasks'
import { track } from '@/lib/analytics'
import { BottomSheet } from '@/ui/BottomSheet'

import { ModelPage } from '../handoff/ModelPage'
import { ModePage } from '../handoff/ModePage'
import {
    defaultRuntimeAdapter,
    type ModelCatalogueState,
    modelAfterEffort,
    modelAfterPick,
} from '../handoff/useRunOptions'
import {
    type ChatRunOptions,
    type ChatRunOptionsAction,
    chatPermissionMode,
    chatRuntimeAdapter,
} from './chatRunOptions'

export type ChatOptionsPage = 'model' | 'mode'

interface ChatOptionsSheetProps {
    visible: boolean
    page: ChatOptionsPage
    catalogue: ModelCatalogueState
    defaults: ResolvedAiRunDefaultsApi | undefined
    options: ChatRunOptions
    /** The open session's harness. A live run cannot switch harness, so the sheet offers only its models. */
    runAdapter: RuntimeAdapterApi | null
    onChange: (action: ChatRunOptionsAction) => void
    onClose: () => void
}

// The option name only, as the hand-off tracks it.
function trackOptionChanged(option: 'model' | 'effort' | 'mode'): void {
    track('mobile_chat_option_changed', { option })
}

/** The chat route is a native modal outside the tab layout's overlay host, so this sheet draws inline over the chat. */
export function ChatOptionsSheet({
    visible,
    page,
    catalogue,
    defaults,
    options,
    runAdapter,
    onChange,
    onClose,
}: ChatOptionsSheetProps): ReactElement {
    const modelListGesture = useMemo(() => Gesture.Native(), [])
    const offered = useMemo(
        (): ModelCatalogueState =>
            runAdapter
                ? {
                      ...catalogue,
                      catalogue: catalogue.catalogue.filter((option) => option.runtime_adapter === runAdapter),
                  }
                : catalogue,
        [catalogue, runAdapter]
    )
    const models = offered.catalogue

    const pickModel = (option: ModelChoiceApi): void => {
        onChange({
            type: 'model',
            model: modelAfterPick(models, defaults, options.model, option),
            runtimeAdapter: option.runtime_adapter,
        })
        trackOptionChanged('model')
    }
    const pickEffort = (effort: ReasoningEffortApi): void => {
        const model = modelAfterEffort(models, defaults, options.model, effort)
        if (!model) {
            return
        }
        onChange({ type: 'model', model, runtimeAdapter: model.runtimeAdapter })
        trackOptionChanged('effort')
    }
    const resetModel = (): void => {
        if (options.model === 'default') {
            return
        }
        onChange({ type: 'model', model: 'default', runtimeAdapter: runAdapter ?? defaultRuntimeAdapter(defaults) })
        trackOptionChanged('model')
    }
    const pickMode = (mode: PermissionModeApi): void => {
        if (mode !== options.permissionMode) {
            onChange({ type: 'mode', mode })
            trackOptionChanged('mode')
        }
        onClose()
    }

    return (
        <BottomSheet
            visible={visible}
            onClose={onClose}
            scrollGesture={page === 'model' ? modelListGesture : undefined}
            accessibilityLabel={page === 'model' ? 'Model and reasoning' : 'Mode'}
            testID="chat-options-sheet"
        >
            {page === 'model' ? (
                <ModelPage
                    catalogue={offered}
                    defaults={defaults}
                    model={options.model}
                    onPickModel={pickModel}
                    onPickEffort={pickEffort}
                    onResetModel={resetModel}
                    listGesture={modelListGesture}
                    onBack={onClose}
                />
            ) : (
                <ModePage
                    runtimeAdapter={chatRuntimeAdapter(options, defaults, runAdapter)}
                    current={chatPermissionMode(options, defaults, runAdapter)}
                    onPick={pickMode}
                    onBack={onClose}
                />
            )}
        </BottomSheet>
    )
}
