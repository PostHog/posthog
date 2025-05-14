import { IconAI, IconCheck, IconPencil, IconPlus, IconX } from '@posthog/icons'
import { LemonButton, LemonInput, LemonTextArea } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Label } from 'lib/ui/Label/Label'
import { useEffect, useRef, useState } from 'react'
import { SceneExport } from 'scenes/sceneTypes'

import { VideoStreamPlayer } from './VideoStreamPlayer'
// import { useActions, useValues } from 'kea' // Uncomment if you use actions/values from logic
import { visionHogConfigLogic } from './visionHogConfiglogic'

export const scene: SceneExport = {
    component: VisionHogConfigScene,
    logic: visionHogConfigLogic,
}

export function VisionHogConfigScene(): JSX.Element {
    const { getConfigSuggestion, removeSuggestion, updateSuggestion, setSuggestions } = useActions(visionHogConfigLogic)
    const { suggestions, suggestionsLoading } = useValues(visionHogConfigLogic)
    const [editingIndex, setEditingIndex] = useState<number | null>(null)
    const [editValue, setEditValue] = useState<string>('')
    const inputRef = useRef<HTMLInputElement>(null)
    const [videoUrl, setVideoUrl] = useState('')
    const [showDescriptionInput, setShowDescriptionInput] = useState(false)
    const [descriptionValue, setDescriptionValue] = useState('')
    const [waitingForSuggestions, setWaitingForSuggestions] = useState(false)

    // Track loading state and hide description input when loading completes
    useEffect(() => {
        if (waitingForSuggestions && !suggestionsLoading) {
            // Loading finished
            setWaitingForSuggestions(false)
            setShowDescriptionInput(false)
            setDescriptionValue('')
        }
    }, [suggestionsLoading, waitingForSuggestions])

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

    const handleAddEvent = (): void => {
        // Add an empty suggestion and put it in edit mode
        const newIndex = suggestions.length

        // Hide description input if it's open
        setShowDescriptionInput(false)

        // Add a new empty suggestion to the list
        setSuggestions([...suggestions, ''])

        // Put it in edit mode
        setTimeout(() => {
            setEditingIndex(newIndex)
            setEditValue('')
            setTimeout(() => {
                inputRef.current?.focus()
            }, 0)
        }, 0)
    }

    const handleDescribeEventsClick = (): void => {
        setShowDescriptionInput(!showDescriptionInput)
        setEditingIndex(null)
    }

    const handleSubmitDescription = (): void => {
        if (descriptionValue.trim()) {
            setWaitingForSuggestions(true)
            getConfigSuggestion(descriptionValue)
            // We'll clear the input and hide the box after loading completes (in useEffect)
        }
    }

    return (
        <div className="flex flex-row gap-6">
            <div className="flex-1 flex flex-col gap-2">
                <Label>Stream link</Label>
                <LemonInput placeholder="https://stream.com/events" value={videoUrl} onChange={setVideoUrl} />
                <VideoStreamPlayer videoUrl={videoUrl} className="my-2" />
            </div>
            <div className="flex-1 flex flex-col gap-2">
                <Label>Events to track</Label>

                {suggestions.length === 0 ? (
                    <div className="flex flex-col gap-2">
                        {showDescriptionInput && (
                            <div className="flex flex-col gap-2 p-3 border rounded bg-bg-light">
                                <LemonTextArea
                                    placeholder="Describe the events you want to track (e.g. 'Track when people pick up coffee, use their phone, or look away from screen')"
                                    value={descriptionValue}
                                    onChange={setDescriptionValue}
                                    className="min-h-[100px]"
                                    disabled={waitingForSuggestions}
                                />
                                <div className="flex justify-end">
                                    <LemonButton
                                        type="primary"
                                        onClick={handleSubmitDescription}
                                        disabledReason={
                                            !descriptionValue.trim() ? 'Please enter a description' : undefined
                                        }
                                        loading={suggestionsLoading}
                                    >
                                        Generate events
                                    </LemonButton>
                                </div>
                            </div>
                        )}
                        <div className="flex flex-row items-center gap-2">
                            <LemonButton type="secondary" icon={<IconPlus />} size="small" onClick={handleAddEvent}>
                                Add event
                            </LemonButton>
                            <LemonButton
                                type="secondary"
                                icon={<IconAI />}
                                size="small"
                                onClick={handleDescribeEventsClick}
                            >
                                Describe events
                            </LemonButton>
                        </div>
                    </div>
                ) : (
                    <div className="flex flex-col gap-2">
                        {suggestions.map((suggestion, index) => (
                            <div
                                key={index}
                                className="flex items-center justify-between p-3 border rounded bg-bg-light"
                            >
                                {editingIndex === index ? (
                                    <div className="flex-1 flex items-center gap-2">
                                        <LemonInput
                                            ref={inputRef}
                                            fullWidth
                                            value={editValue}
                                            onChange={setEditValue}
                                            onKeyDown={handleKeyDown}
                                        />
                                        <LemonButton
                                            icon={<IconCheck />}
                                            size="small"
                                            onClick={handleSave}
                                            type="primary"
                                            className="flex-shrink-0"
                                            tooltip="Save changes"
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
                        <div className="flex flex-col gap-2">
                            {showDescriptionInput && (
                                <div className="flex flex-col gap-2 p-3 border rounded bg-bg-light">
                                    <LemonTextArea
                                        placeholder="Describe the events you want to track (e.g. 'Track when people pick up coffee, use their phone, or look away from screen')"
                                        value={descriptionValue}
                                        onChange={setDescriptionValue}
                                        className="min-h-[100px]"
                                        disabled={waitingForSuggestions}
                                    />
                                    <div className="flex justify-end">
                                        <LemonButton
                                            type="primary"
                                            onClick={handleSubmitDescription}
                                            disabledReason={
                                                !descriptionValue.trim() ? 'Please enter a description' : undefined
                                            }
                                            loading={suggestionsLoading}
                                        >
                                            Generate events
                                        </LemonButton>
                                    </div>
                                </div>
                            )}
                            <div className="flex flex-row items-center gap-2">
                                <LemonButton type="secondary" icon={<IconPlus />} size="small" onClick={handleAddEvent}>
                                    Add event
                                </LemonButton>
                                <LemonButton
                                    type="secondary"
                                    icon={<IconAI />}
                                    size="small"
                                    onClick={handleDescribeEventsClick}
                                >
                                    Describe events
                                </LemonButton>
                            </div>
                        </div>
                    </div>
                )}
            </div>
        </div>
    )
}
