import { IconPencil, IconX } from '@posthog/icons'
import { LemonButton, LemonInput, LemonTextArea } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Label } from 'lib/ui/Label/Label'
import { useRef, useState } from 'react'
import { SceneExport } from 'scenes/sceneTypes'

// import { useActions, useValues } from 'kea' // Uncomment if you use actions/values from logic
import { visionHogConfigLogic } from './visionHogConfiglogic'

export const scene: SceneExport = {
    component: VisionHogConfigScene,
    logic: visionHogConfigLogic,
}

export function VisionHogConfigScene(): JSX.Element {
    const [configSuggestion, setConfigSuggestion] = useState<string | undefined>(undefined)
    const { getConfigSuggestion, removeSuggestion, updateSuggestion } = useActions(visionHogConfigLogic)
    const { suggestions, suggestionsLoading } = useValues(visionHogConfigLogic)
    const [editingIndex, setEditingIndex] = useState<number | null>(null)
    const [editValue, setEditValue] = useState<string>('')
    const inputRef = useRef<HTMLInputElement>(null)

    const handleEdit = (index: number, value: string): void => {
        setEditingIndex(index)
        setEditValue(value)
        // Focus the input after it renders
        setTimeout(() => {
            inputRef.current?.focus()
        }, 0)
    }

    const handleSave = (): void => {
        if (editingIndex !== null) {
            updateSuggestion(editingIndex, editValue)
            setEditingIndex(null)
        }
    }

    const handleKeyDown = (e: React.KeyboardEvent): void => {
        if (e.key === 'Enter') {
            handleSave()
        } else if (e.key === 'Escape') {
            setEditingIndex(null)
        }
    }

    return (
        <div className="flex flex-row gap-6">
            <div className="flex-1 flex flex-col gap-2">
                <Label>Stream link</Label>
                <LemonInput placeholder="https://stream.com/events" />

                <Label>Stream events</Label>
                <LemonTextArea
                    placeholder="Track every moment a person picks up their coffee "
                    value={configSuggestion}
                    onChange={(v) => setConfigSuggestion(v)}
                />
                <div className="flex justify-end">
                    <LemonButton
                        disabledReason={!configSuggestion ? 'Please enter a prompt' : undefined}
                        type="primary"
                        loading={suggestionsLoading}
                        onClick={() => configSuggestion && getConfigSuggestion(configSuggestion)}
                    >
                        Get config suggestion
                    </LemonButton>
                </div>
            </div>
            <div className="flex-1 flex flex-col gap-2">
                <Label>Events to track</Label>
                {suggestions.length === 0 ? (
                    <div className="text-muted text-sm p-2">No suggestions yet</div>
                ) : (
                    <div className="flex flex-col gap-2">
                        {suggestions.map((suggestion, index) => (
                            <div
                                key={index}
                                className="flex items-center justify-between p-3 border rounded bg-bg-light"
                            >
                                {editingIndex === index ? (
                                    <div className="flex-1 flex items-center">
                                        <LemonInput
                                            ref={inputRef}
                                            fullWidth
                                            value={editValue}
                                            onChange={setEditValue}
                                            onBlur={handleSave}
                                            onKeyDown={handleKeyDown}
                                        />
                                    </div>
                                ) : (
                                    <div className="flex-1 break-words">{suggestion}</div>
                                )}
                                <div className="flex items-center gap-1 ml-2 flex-shrink-0">
                                    {editingIndex !== index && (
                                        <LemonButton
                                            icon={<IconPencil />}
                                            size="small"
                                            onClick={() => handleEdit(index, suggestion)}
                                            tooltip="Edit suggestion"
                                        />
                                    )}
                                    <LemonButton
                                        icon={<IconX />}
                                        size="small"
                                        onClick={() => removeSuggestion(index)}
                                        className="flex-shrink-0"
                                        tooltip="Remove suggestion"
                                    />
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </div>
    )
}
