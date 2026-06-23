import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'

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
        actions: [sandboxStreamLogic({ streamKey: props.runId }), ['pushHumanMessage']],
    })),

    actions({
        sendMessage: (content: string) => ({ content }),
        setSendingMessage: (sending: boolean) => ({ sending }),
        setComposerDraft: (draft: string) => ({ draft }),
        clearComposerDraft: true,
    }),

    reducers({
        sendingMessage: [
            false,
            {
                setSendingMessage: (_, { sending }) => sending,
            },
        ],
        composerDraft: [
            '',
            {
                setComposerDraft: (_, { draft }) => draft,
                clearComposerDraft: () => '',
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
                // Only clear the draft once the send succeeds — a failed send (or missing project) keeps
                // the user's text so they can retry without retyping.
                actions.clearComposerDraft()
            } catch {
                lemonToast.error('Failed to send message. Please try again.')
            } finally {
                actions.setSendingMessage(false)
            }
        },
    })),
])
