import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useRef } from 'react'

import { Tooltip } from '@posthog/lemon-ui'

import { LemonBadge } from 'lib/lemon-ui/LemonBadge'

import { workflowLogic } from '../../../workflowLogic'
import { NODE_HEIGHT, NODE_WIDTH } from '../../constants'
import { hogFlowEditorLogic } from '../../hogFlowEditorLogic'
import { HogFlowAction } from '../../types'
import { useHogFlowStep } from '../HogFlowSteps'
import { StepViewMetrics } from './StepViewMetrics'
import { StepViewLogicProps, stepViewLogic } from './stepViewLogic'

export function StepView({ action }: { action: HogFlowAction }): JSX.Element {
    const { selectedNode, mode } = useValues(hogFlowEditorLogic)
    const { actionValidationErrorsById, logicProps } = useValues(workflowLogic)
    const isSelected = selectedNode?.id === action.id
    const inputRef = useRef<HTMLInputElement>(null)
    const descriptionInputRef = useRef<HTMLTextAreaElement>(null)

    const stepViewLogicProps: StepViewLogicProps = { action, workflowLogicProps: logicProps }
    const { isEditingName, isEditingDescription, editNameValue, editDescriptionValue } = useValues(
        stepViewLogic(stepViewLogicProps)
    )
    const {
        startEditingName,
        startEditingDescription,
        setEditNameValue,
        setEditDescriptionValue,
        saveName,
        saveDescription,
        cancelEditingName,
        cancelEditingDescription,
    } = useActions(stepViewLogic(stepViewLogicProps))

    const height = mode === 'metrics' ? NODE_HEIGHT + 10 : NODE_HEIGHT

    const Step = useHogFlowStep(action)
    const { selectedColor, colorLight, color, icon } = useMemo(() => {
        return {
            selectedColor: Step?.color
                ? isSelected
                    ? `${Step?.color}`
                    : `${Step?.color}20`
                : isSelected
                  ? 'var(--border-primary)'
                  : 'var(--border)',
            colorLight: Step?.color ? `${Step?.color}20` : 'var(--border)',
            color: Step?.color || 'var(--text-secondary)',
            icon: Step?.icon,
        }
    }, [action, isSelected, Step])

    const hasValidationError = actionValidationErrorsById[action.id]?.valid === false

    useEffect(() => {
        if (isEditingName && inputRef.current) {
            inputRef.current.focus()
            const length = inputRef.current.value.length
            inputRef.current.setSelectionRange(length, length)
        }
    }, [isEditingName])

    useEffect(() => {
        if (isEditingDescription && descriptionInputRef.current) {
            descriptionInputRef.current.focus()
            const length = descriptionInputRef.current.value.length
            descriptionInputRef.current.setSelectionRange(length, length)
        }
    }, [isEditingDescription])

    return (
        <div
            className="relative flex flex-col cursor-pointer rounded user-select-none bg-surface-primary"
            style={{
                width: NODE_WIDTH,
                height,
                borderWidth: 1,
                borderColor: selectedColor,
                boxShadow: `0px 2px 0px 0px ${colorLight}`,
                zIndex: 0,
            }}
        >
            {/* Content layer */}
            <div className="relative z-10 flex gap-1 p-1 items-start w-full">
                <div
                    className="flex justify-center h-6 items-center aspect-square rounded"
                    style={{
                        backgroundColor: colorLight,
                        color,
                    }}
                >
                    {icon}
                </div>
                <div className="flex flex-col flex-1 min-w-0">
                    <div className="flex justify-between items-center gap-1">
                        {isEditingName ? (
                            <input
                                ref={inputRef}
                                type="text"
                                value={editNameValue}
                                onChange={(e) => setEditNameValue(e.target.value)}
                                onBlur={(e) => {
                                    e.stopPropagation()
                                    saveName()
                                    e.currentTarget.blur()
                                }}
                                onKeyDown={(e) => {
                                    e.stopPropagation()
                                    if (e.key === 'Enter') {
                                        e.preventDefault()
                                        saveName()
                                        e.currentTarget.blur()
                                    } else if (e.key === 'Escape') {
                                        e.preventDefault()
                                        cancelEditingName()
                                        e.currentTarget.blur()
                                    }
                                }}
                                onClick={(e) => e.stopPropagation()}
                                onMouseDown={(e) => e.stopPropagation()}
                                className="text-[0.45rem] font-sans font-medium bg-transparent border-0 outline-none pl-1 pr-0 py-0 m-0 w-full focus:ring-1 focus:ring-primary focus:ring-offset-0 rounded"
                                style={{ color: 'inherit' }}
                            />
                        ) : (
                            <Tooltip title={action.name}>
                                <div
                                    className="text-[0.45rem] font-sans font-medium cursor-text hover:bg-fill-button-tertiary-hover rounded px-0.5 -mx-0.5 transition-colors pl-1 truncate min-w-0 flex-1"
                                    onClick={(e) => {
                                        e.stopPropagation()
                                        startEditingName()
                                    }}
                                    onMouseDown={(e) => e.stopPropagation()}
                                >
                                    {action.name}
                                </div>
                            </Tooltip>
                        )}
                    </div>

                    {isEditingDescription ? (
                        <textarea
                            ref={descriptionInputRef}
                            value={editDescriptionValue}
                            onChange={(e) => setEditDescriptionValue(e.target.value)}
                            onBlur={(e) => {
                                e.stopPropagation()
                                saveDescription()
                                e.currentTarget.blur()
                            }}
                            onKeyDown={(e) => {
                                e.stopPropagation()
                                if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                                    e.preventDefault()
                                    saveDescription()
                                    e.currentTarget.blur()
                                } else if (e.key === 'Escape') {
                                    e.preventDefault()
                                    cancelEditingDescription()
                                    e.currentTarget.blur()
                                }
                            }}
                            onClick={(e) => e.stopPropagation()}
                            onMouseDown={(e) => e.stopPropagation()}
                            className="text-[0.3rem]/1.5 text-muted bg-transparent border-0 outline-none pl-1 pr-0 py-0 m-0 w-full focus:ring-1 focus:ring-primary focus:ring-offset-0 rounded resize-none overflow-hidden"
                            style={{ color: 'inherit', height: '0.9rem', lineHeight: '1.5' }}
                        />
                    ) : (
                        <Tooltip title={action.description || ''}>
                            <div
                                className="text-[0.3rem]/1.5 text-muted line-clamp-2 cursor-text hover:bg-fill-button-tertiary-hover rounded px-0.5 -mx-0.5 transition-colors pl-1 min-w-0 overflow-hidden"
                                onClick={(e) => {
                                    e.stopPropagation()
                                    startEditingDescription()
                                }}
                                onMouseDown={(e) => e.stopPropagation()}
                            >
                                {action.description || ''}
                            </div>
                        </Tooltip>
                    )}
                </div>
            </div>
            {hasValidationError && (
                <div className="absolute top-0 right-0 scale-75">
                    <LemonBadge status="warning" size="small" content="!" position="top-right" />
                </div>
            )}
            {mode === 'metrics' && (
                <div
                    style={{
                        borderTopColor: colorLight,
                        borderTopWidth: 1,
                    }}
                >
                    <StepViewMetrics action={action} />
                </div>
            )}
        </div>
    )
}
