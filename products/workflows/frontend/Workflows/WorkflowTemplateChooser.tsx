import clsx from 'clsx'
import FuseClass from 'fuse.js'
import { useActions, useValues } from 'kea'
import React, { useState } from 'react'

import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog } from '@posthog/lemon-ui'

import { FallbackCoverImage } from 'lib/components/FallbackCoverImage/FallbackCoverImage'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { Spinner } from 'lib/lemon-ui/Spinner'

import BlankWorkflowHog from 'public/blank-dashboard-hog.png'

import type { HogFlow } from './hogflows/types'
import { newWorkflowLogic } from './newWorkflowLogic'
import { workflowsLogic } from './workflowsLogic'

export function WorkflowTemplateChooser(): JSX.Element {
    const { workflowTemplates, workflowTemplatesLoading, templateFilter } = useValues(workflowsLogic)
    const { deleteHogflowTemplate } = useActions(workflowsLogic)

    const { createWorkflowFromTemplate, createEmptyWorkflow } = useActions(newWorkflowLogic)

    const filteredTemplates = React.useMemo(() => {
        if (!templateFilter) {
            return workflowTemplates
        }
        const fuse = new FuseClass(workflowTemplates, {
            keys: [{ name: 'name', weight: 2 }, 'description'],
            threshold: 0.3,
            ignoreLocation: true,
        })
        return fuse.search(templateFilter).map((result) => result.item)
    }, [workflowTemplates, templateFilter])

    return (
        <div>
            <div className="grid grid-cols-[repeat(auto-fill,minmax(200px,1fr))] gap-4 py-4">
                <TemplateItem
                    template={{
                        name: 'Empty workflow',
                        description: 'Create a blank workflow from scratch',
                        image_url: BlankWorkflowHog,
                    }}
                    onClick={createEmptyWorkflow}
                    index={0}
                    data-attr="create-workflow-blank"
                />
                {workflowTemplatesLoading ? (
                    <Spinner className="text-6xl" />
                ) : (
                    filteredTemplates.map((template, index) => (
                        <TemplateItem
                            key={template.id}
                            template={template}
                            onClick={() => createWorkflowFromTemplate(template)}
                            onDelete={(e) => {
                                e.stopPropagation()
                                LemonDialog.open({
                                    title: 'Delete template?',
                                    // TODOdin: Put in a proper warning for situations where this will remove the template for EVERYONE
                                    // (Maybe make them type "everyone" to confirm)
                                    description: `Are you sure you want to delete "${template.name}"? This action cannot be undone and may affect more than just your team.`,
                                    primaryButton: {
                                        children: 'Delete',
                                        status: 'danger',
                                        onClick: async () => {
                                            try {
                                                await deleteHogflowTemplate(template)
                                                lemonToast.success(`Template "${template.name}" deleted`)
                                            } catch (error: any) {
                                                lemonToast.error(
                                                    `Failed to delete template: ${error.detail || error.message || 'Unknown error'}`
                                                )
                                            }
                                        },
                                    },
                                    secondaryButton: { children: 'Cancel' },
                                })
                            }}
                            index={index + 1}
                            data-attr="create-workflow-from-template"
                        />
                    ))
                )}
            </div>
        </div>
    )
}

function TemplateItem({
    template,
    onClick,
    onDelete,
    index,
    'data-attr': dataAttr,
}: {
    template: Pick<HogFlow, 'name' | 'description'> & { image_url?: string }
    onClick: () => void
    onDelete?: (e: React.MouseEvent) => void
    index: number
    'data-attr': string
}): JSX.Element {
    const [isHovering, setIsHovering] = useState(false)

    return (
        <div
            className="cursor-pointer border rounded flex flex-col transition-all relative min-h-[200px] bg-bg-light hover:border-primary hover:shadow-md"
            onClick={onClick}
            onMouseEnter={() => setIsHovering(true)}
            onMouseLeave={() => setIsHovering(false)}
            data-attr={dataAttr}
        >
            {onDelete && (
                <div className="absolute top-2 right-2 z-10">
                    <LemonButton
                        icon={<IconTrash />}
                        size="small"
                        status="danger"
                        onClick={onDelete}
                        tooltip="Delete template"
                    />
                </div>
            )}
            <div
                className={clsx('transition-all w-full overflow-hidden', isHovering ? 'h-4 min-h-4' : 'h-30 min-h-30')}
            >
                <FallbackCoverImage src={template?.image_url} alt="cover photo" index={index} imageClassName="h-30" />
            </div>

            <h5 className="px-2 mb-1">{template?.name || 'Unnamed template'}</h5>
            <div className="px-2 py-1 overflow-y-auto grow">
                <p className={clsx('text-secondary text-xs', isHovering ? '' : 'line-clamp-2')}>
                    {template?.description ?? ' '}
                </p>
            </div>
        </div>
    )
}
