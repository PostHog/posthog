import './WorkflowTemplateChooser.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import { IconPencil, IconTrash } from '@posthog/icons'
import { LemonDialog, LemonTag } from '@posthog/lemon-ui'

import { FallbackCoverImage } from 'lib/components/FallbackCoverImage/FallbackCoverImage'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import BlankWorkflowHog from 'public/blank-dashboard-hog.png'

import type { HogFlowTemplate } from './hogflows/types'
import { newWorkflowLogic } from './newWorkflowLogic'
import { workflowTemplatesLogic } from './workflowTemplatesLogic'

// Adapted from DashboardTemplateChooser.tsx; try to keep parity for a consistent user experience
export function WorkflowTemplateChooser(): JSX.Element {
    const { filteredTemplates, workflowTemplatesLoading } = useValues(workflowTemplatesLogic)
    const { deleteHogflowTemplate } = useActions(workflowTemplatesLogic)
    const canCreateTemplates = useFeatureFlag('WORKFLOWS_TEMPLATE_CREATION')
    const { user } = useValues(userLogic)

    const { createWorkflowFromTemplate, createEmptyWorkflow } = useActions(newWorkflowLogic)

    const canManageTemplate = (template: HogFlowTemplate): boolean => {
        if (!canCreateTemplates) {
            return false
        }
        if (template.scope === 'global') {
            return user?.is_staff ?? false
        }

        return true
    }

    return (
        <div>
            <div className="WorkflowTemplateChooser">
                <TemplateItem
                    key={0}
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
                    filteredTemplates.map((template: HogFlowTemplate, index: number) => (
                        <TemplateItem
                            key={template.id}
                            template={template}
                            onClick={() => createWorkflowFromTemplate(template)}
                            onEdit={
                                canManageTemplate(template)
                                    ? (e) => {
                                          e.stopPropagation()
                                          router.actions.push(urls.workflowNew(), { editTemplateId: template.id })
                                      }
                                    : undefined
                            }
                            onDelete={
                                canManageTemplate(template)
                                    ? (e) => {
                                          e.stopPropagation()
                                          LemonDialog.open({
                                              title: 'Delete template?',
                                              description: (
                                                  <>
                                                      Are you sure you want to delete "{template.name}"?
                                                      <br />
                                                      This action cannot be undone
                                                      {template.scope === 'team'
                                                          ? '!'
                                                          : ' and will affect all posthog users!'}
                                                  </>
                                              ),
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
                                      }
                                    : undefined
                            }
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
    onEdit,
    onDelete,
    index,
    'data-attr': dataAttr,
}: {
    template: Pick<HogFlowTemplate, 'name' | 'description' | 'image_url' | 'scope'>
    onClick: () => void
    onEdit?: (e: React.MouseEvent) => void
    onDelete?: (e: React.MouseEvent) => void
    index: number
    'data-attr': string
}): JSX.Element {
    const [isHovering, setIsHovering] = useState(false)
    const [isMenuOpen, setIsMenuOpen] = useState(false)

    const scopeTag = template.scope === 'global' ? 'official' : template.scope === 'team' ? 'team' : null

    return (
        <div
            className="cursor-pointer border rounded TemplateItem flex flex-col transition-all relative"
            onClick={onClick}
            onMouseEnter={() => setIsHovering(true)}
            onMouseLeave={() => setIsHovering(false)}
            data-attr={dataAttr}
        >
            {(onEdit || onDelete) && (
                <div className="absolute top-2 right-2 z-10" onClick={(e) => e.stopPropagation()}>
                    <More
                        size="small"
                        className="bg-white/20 dark:bg-white/10 backdrop-blur-sm hover:bg-white/40 dark:hover:bg-white/20 transition-colors"
                        dropdown={{
                            visible: isMenuOpen,
                            onVisibilityChange: setIsMenuOpen,
                            closeOnClickInside: true,
                        }}
                        overlay={
                            <LemonMenuOverlay
                                items={[
                                    ...(onEdit
                                        ? [
                                              {
                                                  label: 'Edit',
                                                  icon: <IconPencil />,
                                                  onClick: (e: any) => {
                                                      setIsMenuOpen(false)
                                                      onEdit(e)
                                                  },
                                              },
                                          ]
                                        : []),
                                    ...(onDelete
                                        ? [
                                              {
                                                  label: 'Delete',
                                                  status: 'danger' as const,
                                                  icon: <IconTrash />,
                                                  onClick: (e: any) => {
                                                      setIsMenuOpen(false)
                                                      onDelete(e)
                                                  },
                                              },
                                          ]
                                        : []),
                                ]}
                            />
                        }
                    />
                </div>
            )}
            <div
                className={clsx('transition-all w-full overflow-hidden', isHovering ? 'h-4 min-h-4' : 'h-30 min-h-30')}
            >
                <FallbackCoverImage
                    src={template?.image_url || undefined}
                    alt="cover photo"
                    index={index}
                    imageClassName="h-30"
                />
            </div>

            <h5 className="px-2 mb-1">{template?.name || 'Unnamed template'}</h5>
            <div className="flex gap-x-1 px-2 mb-1">
                {scopeTag && (
                    <LemonTag key="scope" type="option">
                        {scopeTag}
                    </LemonTag>
                )}
            </div>
            <div className={clsx('px-2 py-1 grow', isHovering ? 'overflow-y-auto' : 'overflow-hidden')}>
                <p className={clsx('text-secondary text-xs', isHovering ? '' : 'line-clamp-2')}>
                    {template?.description ?? ' '}
                </p>
            </div>
        </div>
    )
}
