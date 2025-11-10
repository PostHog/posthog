import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonInput, LemonTextArea, Tooltip } from '@posthog/lemon-ui'

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
                            <div onClick={(e) => e.stopPropagation()} className="flex-1 min-w-0">
                                <LemonInput
                                    autoFocus
                                    value={editNameValue}
                                    onChange={setEditNameValue}
                                    onBlur={(e: React.FocusEvent) => {
                                        e.stopPropagation()
                                        saveName()
                                    }}
                                    onKeyDown={(e: React.KeyboardEvent) => {
                                        e.stopPropagation()
                                        if (e.key === 'Enter') {
                                            e.preventDefault()
                                            saveName()
                                            ;(e.target as HTMLInputElement).blur()
                                        } else if (e.key === 'Escape') {
                                            e.preventDefault()
                                            cancelEditingName()
                                            ;(e.target as HTMLInputElement).blur()
                                        }
                                    }}
                                    className="text-[0.45rem] font-sans font-medium !bg-transparent !border-0 !shadow-none !p-0 !pl-1 !m-0 !min-h-0 !h-[0.55rem] !leading-tight focus-within:!ring-1 focus-within:!ring-primary !rounded"
                                />
                            </div>
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
                        <div onClick={(e) => e.stopPropagation()} className="min-w-0">
                            <LemonTextArea
                                autoFocus
                                value={editDescriptionValue}
                                onChange={setEditDescriptionValue}
                                onBlur={(e: React.FocusEvent) => {
                                    e.stopPropagation()
                                    saveDescription()
                                }}
                                onKeyDown={(e: React.KeyboardEvent) => {
                                    e.stopPropagation()
                                    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                                        e.preventDefault()
                                        saveDescription()
                                        ;(e.target as HTMLTextAreaElement).blur()
                                    } else if (e.key === 'Escape') {
                                        e.preventDefault()
                                        cancelEditingDescription()
                                        ;(e.target as HTMLTextAreaElement).blur()
                                    }
                                }}
                                className="text-[0.3rem] text-muted !bg-transparent !border-0 !shadow-none !p-0 !pl-1 !m-0 !min-h-0 !max-h-[0.9rem] !leading-[0.45rem] !resize-none !overflow-hidden focus-within:!ring-1 focus-within:!ring-primary !rounded"
                            />
                        </div>
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
