import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { projectLogic } from 'scenes/projectLogic'

import { isTerminalRunStatus, sandboxStreamLogic } from 'products/posthog_ai/frontend/sandbox'
import { tasksRunsCommandCreate } from 'products/tasks/frontend/generated/api'

import type { taskRunChatLogicType } from './taskRunChatLogicType'

export interface TaskRunChatLogicProps {
    taskId: string
    runId: string
}

export const taskRunChatLogic = kea<taskRunChatLogicType>([
    path(['products', 'tasks', 'logics', 'taskRunChatLogic']),
    props({} as TaskRunChatLogicProps),
    key((props) => props.runId),

    connect((props: TaskRunChatLogicProps) => ({
        values: [
            projectLogic,
            ['currentProjectId'],
            sandboxStreamLogic({ streamKey: props.runId }),
            ['currentRunStatus'],
        ],
        actions: [sandboxStreamLogic({ streamKey: props.runId }), ['bootstrapRun', 'pushHumanMessage', 'reset']],
    })),

    actions({
        sendMessage: (content: string) => ({ content }),
        setSendingMessage: (sending: boolean) => ({ sending }),
    }),

    reducers({
        sendingMessage: [
            false,
            {
                setSendingMessage: (_, { sending }) => sending,
            },
        ],
    }),

    selectors({
        isTerminal: [(s) => [s.currentRunStatus], (status): boolean => isTerminalRunStatus(status)],
    }),

    listeners(({ actions, values, props }) => ({
        sendMessage: async ({ content }) => {
            if (values.sendingMessage || !content.trim() || values.isTerminal) {
                return
            }
            if (values.currentProjectId == null) {
                return
            }
            actions.setSendingMessage(true)
            try {
                await tasksRunsCommandCreate(String(values.currentProjectId), props.taskId, props.runId, {
                    jsonrpc: '2.0',
                    method: 'user_message',
                    params: { content },
                })
                actions.pushHumanMessage(content)
            } catch {
                lemonToast.error('Failed to send message. Please try again.')
            } finally {
                actions.setSendingMessage(false)
            }
        },
    })),

    afterMount(({ props, actions }) => {
        // sandboxStreamLogic is already bound (the BindLogic in TaskRunChat mounts it first), so a
        // reset + bootstrapRun here re-bootstraps cleanly when a reused logic instance is remounted.
        // Live vs. replay mode is resolved inside bootstrapRun from the run status the tasks API returns.
        actions.reset()
        actions.bootstrapRun({ taskId: props.taskId, runId: props.runId })
    }),
])
