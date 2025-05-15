import { IconCheck, IconChevronDown, IconPencil, IconPlus, IconX } from '@posthog/icons'
import { LemonButton, LemonInput, LemonTextArea } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Label } from 'lib/ui/Label/Label'
import { useEffect, useRef, useState } from 'react'
import { SceneExport } from 'scenes/sceneTypes'

import { VideoStreamPlayer } from './VideoStreamPlayer'
import { ConfigState, EventConfig, visionHogConfigLogic } from './visionHogConfiglogic'

// Add keyframes for the pop-up animation
const buttonAnimationStyles = `
.pop-up-animation {
    animation: 0.4s ease-out forwards;
}

.event-card {
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 12px;
    margin-bottom: 8px;
    background-color: var(--bg-light);
}

.event-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
}

.property-card {
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 8px;
    margin-top: 8px;
    background-color: var(--bg-3000);
}

.property-list {
    margin-top: 10px;
}

.event-description, .property-description {
    font-size: 13px;
    color: var(--muted);
    margin-top: 4px;
}

.event-details {
    padding-top: 8px;
    margin-top: 8px;
}

.properties-container {
    background-color: white;
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 12px;
    margin-top: 8px;
}

.collapsible-section {
    margin-top: 8px;
}
`

export const scene: SceneExport = {
    component: VisionHogConfigScene,
    logic: visionHogConfigLogic,
}

export function VisionHogConfigScene(): JSX.Element {
    const {
        getConfigSuggestion,
        removeSuggestion,
        updateSuggestion,
        setSuggestions,
        setUrl,
        saveStreamConfig,
        addPropertyToEvent,
        updateEventProperty,
        removeEventProperty,
    } = useActions(visionHogConfigLogic)
    const { suggestions, suggestionsLoading, url, configState } = useValues(visionHogConfigLogic)

    // State for event editing
    const [editingEventIndex, setEditingEventIndex] = useState<number | null>(null)
    const [editEventNameValue, setEditEventNameValue] = useState<string>('')
    const [editEventDescValue, setEditEventDescValue] = useState<string>('')
    const eventNameInputRef = useRef<HTMLInputElement>(null)

    // State for property editing
    const [editingPropertyIndices, setEditingPropertyIndices] = useState<{
        eventIndex: number
        propertyIndex: number
    } | null>(null)
    const [editPropertyNameValue, setEditPropertyNameValue] = useState<string>('')
    const [editPropertyDescValue, setEditPropertyDescValue] = useState<string>('')
    const propertyNameInputRef = useRef<HTMLInputElement>(null)

    // UI state
    const [showDescriptionInput, setShowDescriptionInput] = useState(false)
    const [descriptionValue, setDescriptionValue] = useState('')
    const [waitingForSuggestions, setWaitingForSuggestions] = useState(false)
    const [expandedEvents, setExpandedEvents] = useState<number[]>([])

    // Track loading state and hide description input when loading completes
    useEffect(() => {
        if (waitingForSuggestions && !suggestionsLoading) {
            // Loading finished
            setWaitingForSuggestions(false)
            setShowDescriptionInput(false)
            setDescriptionValue('')
        }
    }, [suggestionsLoading, waitingForSuggestions])

    // Toggle event expansion
    const toggleEventExpansion = (index: number): void => {
        if (expandedEvents.includes(index)) {
            setExpandedEvents(expandedEvents.filter((i) => i !== index))
        } else {
            setExpandedEvents([...expandedEvents, index])
        }
    }

    // Event editing handlers
    const handleEditEvent = (index: number, event: EventConfig): void => {
        setEditingEventIndex(index)
        setEditEventNameValue(event.name)
        setEditEventDescValue(event.description)
        // Focus the input after it renders
        setTimeout(() => {
            eventNameInputRef.current?.focus()
        }, 0)
    }

    const handleSaveEvent = (): void => {
        if (editingEventIndex !== null) {
            updateSuggestion(editingEventIndex, {
                name: editEventNameValue,
                description: editEventDescValue,
            })
            setEditingEventIndex(null)
        }
    }

    const handleEventKeyDown = (e: React.KeyboardEvent): void => {
        if (e.key === 'Enter' && !e.shiftKey) {
            handleSaveEvent()
        } else if (e.key === 'Escape') {
            setEditingEventIndex(null)
        }
    }

    // Property editing handlers
    const handleEditProperty = (
        eventIndex: number,
        propertyIndex: number,
        propertyName: string,
        propertyDesc: string
    ): void => {
        setEditingPropertyIndices({ eventIndex, propertyIndex })
        setEditPropertyNameValue(propertyName)
        setEditPropertyDescValue(propertyDesc)
        // Focus the input after it renders
        setTimeout(() => {
            propertyNameInputRef.current?.focus()
        }, 0)
    }

    const handleSaveProperty = (): void => {
        if (editingPropertyIndices) {
            const { eventIndex, propertyIndex } = editingPropertyIndices
            updateEventProperty(eventIndex, propertyIndex, {
                name: editPropertyNameValue,
                description: editPropertyDescValue,
            })
            setEditingPropertyIndices(null)
        }
    }

    const handlePropertyKeyDown = (e: React.KeyboardEvent): void => {
        if (e.key === 'Enter' && !e.shiftKey) {
            handleSaveProperty()
        } else if (e.key === 'Escape') {
            setEditingPropertyIndices(null)
        }
    }

    const handleAddEvent = (): void => {
        // Hide description input if it's open
        setShowDescriptionInput(false)

        // Add a new empty suggestion to the list
        setSuggestions([...suggestions, { name: '', description: '', properties: [] }])

        // Put it in edit mode
        const newIndex = suggestions.length
        setTimeout(() => {
            setEditingEventIndex(newIndex)
            setEditEventNameValue('')
            setEditEventDescValue('')
            setTimeout(() => {
                eventNameInputRef.current?.focus()
            }, 0)
        }, 0)
    }

    const handleSubmitDescription = (): void => {
        if (descriptionValue.trim()) {
            setWaitingForSuggestions(true)
            getConfigSuggestion(descriptionValue)
            // We'll clear the input and hide the box after loading completes (in useEffect)
        }
    }

    // Determine if save button should be shown
    const shouldShowSaveButton =
        url.trim() !== '' && suggestions.length > 0 && suggestions.every((s) => s.name.trim() !== '')

    return (
        <div className="relative pb-16">
            {/* Inject the animation styles */}
            <style>{buttonAnimationStyles}</style>

            <div className="flex flex-row gap-6">
                <div className="flex-1 flex flex-col gap-2">
                    <Label>Stream link</Label>
                    <LemonInput placeholder="https://stream.com/events" value={url} onChange={setUrl} />
                    <VideoStreamPlayer videoUrl={url} className="my-2" />
                </div>
                <div className="flex-1 flex flex-col gap-2">
                    <Label>Events to track</Label>

                    {suggestions.length === 0 ? (
                        <div className="flex flex-col gap-2">
                            {showDescriptionInput && (
                                <div className="flex flex-col gap-2 p-3 border rounded bg-bg-light">
                                    <div className="flex justify-between mb-2">
                                        <div className="font-medium">Describe events to generate</div>
                                        <LemonButton
                                            size="small"
                                            icon={<IconX />}
                                            onClick={() => setShowDescriptionInput(false)}
                                            tooltip="Close"
                                        />
                                    </div>
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
                                    New event
                                </LemonButton>
                            </div>
                        </div>
                    ) : (
                        <div className="flex flex-col gap-2">
                            {suggestions.map((event, eventIndex) => (
                                <div key={eventIndex} className="event-card">
                                    {/* Event header */}
                                    <div className="event-header">
                                        {editingEventIndex === eventIndex ? (
                                            <div className="flex-1 flex items-center gap-2">
                                                <div className="flex-1 flex flex-col gap-2">
                                                    <LemonInput
                                                        ref={eventNameInputRef}
                                                        fullWidth
                                                        placeholder="Event name"
                                                        value={editEventNameValue}
                                                        onChange={setEditEventNameValue}
                                                        onKeyDown={handleEventKeyDown}
                                                    />
                                                    <LemonTextArea
                                                        placeholder="Event description (optional)"
                                                        value={editEventDescValue}
                                                        onChange={setEditEventDescValue}
                                                        onKeyDown={handleEventKeyDown}
                                                    />
                                                </div>
                                                <div className="flex-shrink-0">
                                                    <LemonButton
                                                        icon={<IconCheck />}
                                                        size="small"
                                                        onClick={handleSaveEvent}
                                                        type="primary"
                                                        className="flex-shrink-0"
                                                        tooltip="Save changes"
                                                    />
                                                </div>
                                            </div>
                                        ) : (
                                            <div className="flex-1 flex flex-col">
                                                <div className="flex items-center gap-2">
                                                    <div className="font-semibold">{event.name}</div>
                                                </div>
                                                {event.description && (
                                                    <div className="event-description">{event.description}</div>
                                                )}
                                            </div>
                                        )}

                                        {editingEventIndex !== eventIndex && (
                                            <div className="flex items-center gap-1 ml-2 flex-shrink-0">
                                                <LemonButton
                                                    size="small"
                                                    icon={
                                                        <IconChevronDown
                                                            className={
                                                                expandedEvents.includes(eventIndex) ? 'rotate-180' : ''
                                                            }
                                                        />
                                                    }
                                                    onClick={() => toggleEventExpansion(eventIndex)}
                                                />
                                                <LemonButton
                                                    icon={<IconPencil />}
                                                    size="small"
                                                    onClick={() => handleEditEvent(eventIndex, event)}
                                                    tooltip="Edit event"
                                                />
                                                <LemonButton
                                                    icon={<IconX />}
                                                    size="small"
                                                    onClick={() => removeSuggestion(eventIndex)}
                                                    className="flex-shrink-0"
                                                    tooltip="Remove event"
                                                />
                                            </div>
                                        )}
                                    </div>

                                    {/* Event properties (visible when expanded) */}
                                    {expandedEvents.includes(eventIndex) && (
                                        <div className="event-details">
                                            <div className="properties-container">
                                                <div className="flex justify-between items-center">
                                                    <Label>Properties</Label>
                                                    <LemonButton
                                                        size="small"
                                                        icon={<IconPlus />}
                                                        onClick={() => addPropertyToEvent(eventIndex)}
                                                        tooltip="Add property"
                                                    >
                                                        Add property
                                                    </LemonButton>
                                                </div>

                                                {/* Property list */}
                                                <div className="property-list">
                                                    {event.properties.length === 0 ? (
                                                        <div className="text-muted text-sm">No properties yet</div>
                                                    ) : (
                                                        event.properties.map((property, propertyIndex) => (
                                                            <div key={propertyIndex} className="property-card">
                                                                {editingPropertyIndices?.eventIndex === eventIndex &&
                                                                editingPropertyIndices?.propertyIndex ===
                                                                    propertyIndex ? (
                                                                    <div className="flex-1 flex items-center gap-2">
                                                                        <div className="flex-1 flex flex-col gap-2">
                                                                            <LemonInput
                                                                                ref={propertyNameInputRef}
                                                                                fullWidth
                                                                                placeholder="Property name"
                                                                                value={editPropertyNameValue}
                                                                                onChange={setEditPropertyNameValue}
                                                                                onKeyDown={handlePropertyKeyDown}
                                                                            />
                                                                            <LemonTextArea
                                                                                placeholder="Property description (optional)"
                                                                                value={editPropertyDescValue}
                                                                                onChange={setEditPropertyDescValue}
                                                                                onKeyDown={handlePropertyKeyDown}
                                                                            />
                                                                        </div>
                                                                        <div className="flex-shrink-0">
                                                                            <LemonButton
                                                                                icon={<IconCheck />}
                                                                                size="small"
                                                                                onClick={handleSaveProperty}
                                                                                type="primary"
                                                                                className="flex-shrink-0"
                                                                                tooltip="Save changes"
                                                                            />
                                                                        </div>
                                                                    </div>
                                                                ) : (
                                                                    <div className="flex justify-between items-center">
                                                                        <div className="flex-1 flex flex-col">
                                                                            <div className="font-medium">
                                                                                {property.name}
                                                                            </div>
                                                                            {property.description && (
                                                                                <div className="property-description">
                                                                                    {property.description}
                                                                                </div>
                                                                            )}
                                                                        </div>
                                                                        <div className="flex items-center gap-1 ml-2 flex-shrink-0">
                                                                            <LemonButton
                                                                                icon={<IconPencil />}
                                                                                size="small"
                                                                                onClick={() =>
                                                                                    handleEditProperty(
                                                                                        eventIndex,
                                                                                        propertyIndex,
                                                                                        property.name,
                                                                                        property.description
                                                                                    )
                                                                                }
                                                                                tooltip="Edit property"
                                                                            />
                                                                            <LemonButton
                                                                                icon={<IconX />}
                                                                                size="small"
                                                                                onClick={() =>
                                                                                    removeEventProperty(
                                                                                        eventIndex,
                                                                                        propertyIndex
                                                                                    )
                                                                                }
                                                                                className="flex-shrink-0"
                                                                                tooltip="Remove property"
                                                                            />
                                                                        </div>
                                                                    </div>
                                                                )}
                                                            </div>
                                                        ))
                                                    )}
                                                </div>
                                            </div>
                                        </div>
                                    )}
                                </div>
                            ))}
                            <div className="flex flex-col gap-2">
                                {showDescriptionInput && (
                                    <div className="flex flex-col gap-2 p-3 border rounded bg-bg-light">
                                        <div className="flex justify-between mb-2">
                                            <div className="font-medium">Describe events to generate</div>
                                            <LemonButton
                                                size="small"
                                                icon={<IconX />}
                                                onClick={() => setShowDescriptionInput(false)}
                                                tooltip="Close"
                                            />
                                        </div>
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
                                    <LemonButton
                                        type="secondary"
                                        icon={<IconPlus />}
                                        size="small"
                                        onClick={handleAddEvent}
                                    >
                                        Add event
                                    </LemonButton>
                                </div>
                            </div>
                        </div>
                    )}
                </div>
            </div>

            {/* Sticky button at the bottom */}

            <div className="fixed bottom-6 left-1/2 transform -translate-x-1/2 pop-up-animation z-10">
                <LemonButton
                    disabledReason={
                        shouldShowSaveButton ? undefined : 'Please enter a valid stream link and event config'
                    }
                    type="primary"
                    size="large"
                    className="shadow-lg"
                    onClick={saveStreamConfig}
                >
                    {configState === ConfigState.CREATE ? 'Save stream' : 'Update stream'}
                </LemonButton>
            </div>
        </div>
    )
}
