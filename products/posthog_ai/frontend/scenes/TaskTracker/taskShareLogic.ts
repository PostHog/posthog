import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import { toast } from '@posthog/quill'

import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { projectLogic } from 'scenes/projectLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { taskChannelsList, tasksPartialUpdate, tasksRetrieve } from 'products/tasks/frontend/generated/api'
import type { ChannelDTOApi, TaskDetailDTOApi } from 'products/tasks/frontend/generated/api.schemas'

export type TaskVisibility = 'private' | 'public' | 'shared'
export type TaskSpace = Pick<ChannelDTOApi, 'id' | 'name' | 'system_role' | 'channel_type'>

export interface TaskShareLogicProps {
    taskId: string
}

interface TaskShareState {
    task: Pick<TaskDetailDTOApi, 'id' | 'channel' | 'created_by'> | null
    spaces: TaskSpace[]
}

function spaceVisibility(space: TaskSpace): TaskVisibility {
    if (space.system_role === 'personal' || space.channel_type === 'personal') {
        return 'private'
    }
    return space.channel_type === 'private' ? 'shared' : 'public'
}

function taskLink(taskId: string): string {
    return urls.absolute(urls.currentProject(urls.aiTask(taskId)))
}

export const taskShareLogic = kea<any>([
    path(['products', 'posthog_ai', 'frontend', 'scenes', 'TaskTracker', 'taskShareLogic']),
    props({} as TaskShareLogicProps),
    key((props: TaskShareLogicProps) => props.taskId),

    connect(() => ({
        values: [projectLogic, ['currentProjectId'], userLogic, ['user']],
    })),

    actions({
        openShareDialog: true,
        closeShareDialog: true,
        setVisibility: (visibility: 'private' | 'public') => ({ visibility }),
        moveToSpace: (spaceId: string, previousSpaceId: string | null, visibility: TaskVisibility | null) => ({
            spaceId,
            previousSpaceId,
            visibility,
        }),
        visibilityChanged: true,
        copyLink: true,
    }),

    loaders(({ props, values }) => ({
        state: [
            { task: null, spaces: [] } as TaskShareState,
            {
                loadState: async (): Promise<TaskShareState> => {
                    const projectId = String(values.currentProjectId)
                    const [task, spaces] = await Promise.all([
                        tasksRetrieve(projectId, props.taskId),
                        taskChannelsList(projectId),
                    ])
                    const rows = Array.isArray(spaces) ? spaces : spaces.results
                    return {
                        task,
                        spaces: rows.map((row) => ({
                            id: String(row.id),
                            name: row.name ?? '',
                            system_role: row.system_role ?? null,
                            channel_type: row.channel_type ?? '',
                        })),
                    }
                },
            },
        ],
    })),

    reducers({
        shareDialogOpen: [
            false,
            {
                openShareDialog: () => true,
                closeShareDialog: () => false,
                visibilityChanged: () => false,
            },
        ],
        visibilityChanging: [
            false,
            {
                setVisibility: () => true,
                moveToSpace: () => true,
                visibilityChanged: () => false,
            },
        ],
    }),

    selectors({
        space: [
            (s: any) => [s.state],
            (state: TaskShareState): TaskSpace | null =>
                state.spaces.find((space) => space.id === state.task?.channel) ?? null,
        ],
        publicSpace: [
            (s: any) => [s.state],
            (state: TaskShareState): TaskSpace | null =>
                state.spaces.find((space) => space.system_role === 'general') ?? null,
        ],
        visibility: [
            (s: any) => [s.space],
            (space: TaskSpace | null): TaskVisibility | null => (space ? spaceVisibility(space) : null),
        ],
        isCreator: [
            (s: any) => [s.state, s.user],
            (state: TaskShareState, user: { uuid: string } | null): boolean =>
                !!state.task?.created_by && !!user && state.task.created_by.uuid === user.uuid,
        ],
    }),

    listeners(({ actions, values, props }) => ({
        setVisibility: ({ visibility }) => {
            const role = visibility === 'private' ? 'personal' : 'general'
            const target = values.state.spaces.find((space: TaskSpace) => space.system_role === role)
            if (!target) {
                toast.error({ title: 'This project has no team space yet.' })
                actions.visibilityChanged()
                return
            }
            actions.moveToSpace(target.id, values.state.task?.channel ?? null, visibility)
        },
        moveToSpace: async ({ spaceId, previousSpaceId, visibility }) => {
            const projectId = String(values.currentProjectId)
            try {
                const updated = await tasksPartialUpdate(projectId, props.taskId, { channel: spaceId })
                actions.loadStateSuccess({ ...values.state, task: { ...values.state.task, channel: updated.channel } })
                posthog.capture('task visibility changed', {
                    task_id: props.taskId,
                    visibility: visibility ?? 'undo',
                })
                if (visibility === 'public') {
                    await copyToClipboard(taskLink(props.taskId), 'task link')
                }
                toast.success(
                    visibility
                        ? {
                              title:
                                  visibility === 'public'
                                      ? 'This task is now public. We copied the link.'
                                      : 'This task is now private',
                              action: previousSpaceId
                                  ? {
                                        label: 'Undo',
                                        onClick: () => actions.moveToSpace(previousSpaceId, null, null),
                                    }
                                  : undefined,
                          }
                        : { title: 'Change undone' }
                )
            } catch (error) {
                toast.error({
                    title: visibility === 'public' ? "Couldn't share the task" : "Couldn't change who can see the task",
                    description: error instanceof Error ? error.message : 'Try again in a moment.',
                })
            } finally {
                actions.visibilityChanged()
            }
        },
        copyLink: async () => {
            await copyToClipboard(taskLink(props.taskId), 'task link')
        },
    })),

    afterMount(({ actions }) => {
        actions.loadState()
    }),
])
