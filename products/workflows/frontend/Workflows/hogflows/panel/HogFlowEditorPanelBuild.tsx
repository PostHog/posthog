import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { IconDrag, IconEllipsis, IconSparkles } from '@posthog/icons'
import { LemonButton, LemonDropdown, LemonInput, LemonTag, SpinnerOverlay } from '@posthog/lemon-ui'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { hogFunctionTemplateListLogic } from 'scenes/hog-functions/list/hogFunctionTemplateListLogic'
import { HogFunctionStatusTag } from 'scenes/hog-functions/misc/HogFunctionStatusTag'
import { teamLogic } from 'scenes/teamLogic'

import { HogFunctionTemplateType } from '~/types'

import { workflowLogic } from '../../workflowLogic'
import { setHogFlowDragImage } from '../dragPreview'
import { CreateActionType, hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { StepView } from '../steps/components/StepView'
import { useHogFlowStep } from '../steps/HogFlowSteps'
import { HogFlowAction } from '../types'
import { destinationStep, isBetaStep, isPickableDestination, workflowStepSections } from '../workflowStepCatalog'

function HogFlowEditorToolbarNode({
    action,
    onActionSelect,
    children,
}: {
    action: CreateActionType
    onActionSelect?: (action: CreateActionType) => void
    children?: React.ReactNode
}): JSX.Element | null {
    const { hideDropzones, setNodeToBeAdded, showDropzones } = useActions(hogFlowEditorLogic)
    const dragPreviewRef = useRef<HTMLDivElement>(null)

    const onDragStart = (event: React.DragEvent): void => {
        setNodeToBeAdded(action)
        showDropzones()
        event.dataTransfer.setData('application/reactflow', action.type)
        event.dataTransfer.effectAllowed = 'move'
        setHogFlowDragImage(event.dataTransfer, dragPreviewRef.current)
    }

    const onDragEnd = (): void => {
        setNodeToBeAdded(null)
        hideDropzones()
    }

    const step = useHogFlowStep(action as HogFlowAction)

    if (!step) {
        return null
    }

    return (
        <>
            <div
                draggable={!onActionSelect}
                onDragStart={onActionSelect ? undefined : onDragStart}
                onDragEnd={onActionSelect ? undefined : onDragEnd}
            >
                <LemonButton
                    icon={<span style={{ color: step.color }}>{step.icon}</span>}
                    sideIcon={onActionSelect ? undefined : <IconDrag />}
                    fullWidth
                    onClick={onActionSelect ? () => onActionSelect(action) : undefined}
                >
                    {children ?? action.name}
                </LemonButton>
            </div>
            {!onActionSelect && (
                <div ref={dragPreviewRef} className="pointer-events-none absolute invisible" aria-hidden="true">
                    <div className="origin-top-left scale-150">
                        <StepView
                            action={{ ...action, id: `drag-preview-${action.type}-${action.name}` } as HogFlowAction}
                        />
                    </div>
                </div>
            )}
        </>
    )
}

function HogFlowEditorToolbarSection({
    title,
    children,
}: {
    title: React.ReactNode
    children: React.ReactNode
}): JSX.Element {
    return (
        <section className="flex flex-col border-t first:border-t-0">
            <div className="border-b px-3 py-2 text-xxs font-semibold uppercase tracking-wide text-secondary">
                {title}
            </div>
            <div className="flex flex-col gap-1.5 p-2">{children}</div>
        </section>
    )
}

function HogFunctionTemplatesChooser({
    onActionSelect,
}: {
    onActionSelect?: (action: CreateActionType) => void
}): JSX.Element {
    const logic = hogFunctionTemplateListLogic({
        type: 'destination',
        customFilterFunction: isPickableDestination,
    })

    const { loading, filteredTemplates, filters } = useValues(logic)
    const { loadHogFunctionTemplates, setFilters } = useActions(logic)

    const [popoverOpen, setPopoverOpen] = useState(false)

    useEffect(() => {
        loadHogFunctionTemplates()
    }, [loadHogFunctionTemplates])

    return (
        <div>
            <LemonDropdown
                closeOnClickInside={false}
                visible={popoverOpen}
                onClickOutside={() => setPopoverOpen(false)}
                placement="bottom-end"
                overlay={
                    <div className="flex flex-col w-100 h-120 flex-1 overflow-hidden gap-1">
                        <LemonInput
                            placeholder="Search..."
                            value={filters.search ?? ''}
                            onChange={(e) => setFilters({ ...filters, search: e })}
                            autoFocus
                        />

                        {loading ? (
                            <SpinnerOverlay />
                        ) : (
                            <ul className="overflow-y-auto flex-1">
                                {filteredTemplates.map((template: HogFunctionTemplateType) => (
                                    <li key={template.type}>
                                        <HogFlowEditorToolbarNode
                                            action={destinationStep(template)}
                                            onActionSelect={onActionSelect}
                                        >
                                            <div className="py-1 flex items-center gap-1 flex-1">
                                                <div className="flex-1">
                                                    <div>{template.name}</div>
                                                    <div className="text-xs text-muted">{template.description}</div>
                                                </div>
                                                {template.status && <HogFunctionStatusTag status={template.status} />}
                                            </div>
                                        </HogFlowEditorToolbarNode>
                                    </li>
                                ))}
                            </ul>
                        )}
                    </div>
                }
            >
                <LemonButton icon={<IconEllipsis />} fullWidth onClick={() => setPopoverOpen(!popoverOpen)}>
                    More
                </LemonButton>
            </LemonDropdown>
        </div>
    )
}

export function HogFlowEditorPanelBuild({
    className,
    onActionSelect,
}: {
    className?: string
    onActionSelect?: (action: CreateActionType) => void
} = {}): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { currentTeam } = useValues(teamLogic)
    const { isRowScopedTrigger } = useValues(workflowLogic)

    const sections = workflowStepSections({ featureFlags, currentTeam, isRowScopedTrigger })

    return (
        <div
            className={`flex flex-col overflow-y-auto${className ? ` ${className}` : ''}`}
            data-attr="workflow-add-action"
        >
            {sections.map((section) => (
                <HogFlowEditorToolbarSection
                    key={section.key}
                    title={
                        section.key === 'ai' ? (
                            <span className="inline-flex items-center gap-1">
                                {section.title} <IconSparkles />
                            </span>
                        ) : (
                            section.title
                        )
                    }
                >
                    {section.steps.map((action, index) => (
                        <HogFlowEditorToolbarNode
                            key={`${action.type}-${index}`}
                            action={action}
                            onActionSelect={onActionSelect}
                        >
                            {isBetaStep(action) ? (
                                <span className="inline-flex items-center gap-1.5">
                                    {action.name}
                                    <LemonTag type="completion">Beta</LemonTag>
                                </span>
                            ) : undefined}
                        </HogFlowEditorToolbarNode>
                    ))}
                    {section.key === 'dispatch' && <HogFunctionTemplatesChooser onActionSelect={onActionSelect} />}
                </HogFlowEditorToolbarSection>
            ))}
        </div>
    )
}
