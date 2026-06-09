import { useActions, useValues } from 'kea'
import { JSX } from 'react'

import { IconSend, IconStopFilled } from '@posthog/icons'
import { LemonButton, LemonTextArea, Tooltip } from '@posthog/lemon-ui'

import { AttachmentButton, AttachmentsBar } from './Attachments'
import { getConfigOptionByCategory } from './configOptions'
import { ModelSelector, ModeSelector, ReasoningEffortSelector } from './ConfigSelectors'
import { taskComposerLogic } from './taskComposerLogic'

export function TaskComposer({ taskId }: { taskId: string }): JSX.Element {
    const logic = taskComposerLogic({ taskId })
    const { draft, pendingFiles, configOptions, agentBusy, sandboxReady, isTerminal, sending } = useValues(logic)
    const { setDraft, addFiles, removeFile, sendMessage, cancelRun, setConfigOption } = useActions(logic)

    const modeOption = getConfigOptionByCategory(configOptions, 'mode')
    const modelOption = getConfigOptionByCategory(configOptions, 'model')
    const thoughtOption = getConfigOptionByCategory(configOptions, 'thought_level')

    const canSend = draft.trim().length > 0 || pendingFiles.length > 0
    const sendDisabledReason = sending ? 'Sending…' : !canSend ? 'Enter a message or attach a file' : undefined

    return (
        <div
            className="flex flex-col rounded-lg border border-border bg-bg-light focus-within:border-accent"
            data-attr="task-composer"
        >
            <AttachmentsBar files={pendingFiles} onRemove={removeFile} />
            <LemonTextArea
                value={draft}
                onChange={setDraft}
                onPressEnter={() => sendMessage()}
                placeholder={
                    isTerminal
                        ? 'Send a message to continue this task…'
                        : sandboxReady
                          ? 'Send a follow-up…'
                          : 'Message will be sent once the run starts…'
                }
                minRows={2}
                maxRows={12}
                className="border-0 bg-transparent focus:!border-0 focus:!shadow-none"
            />
            <div className="flex items-center gap-1 px-2 py-1.5">
                <AttachmentButton onAddFiles={addFiles} />
                <ModeSelector
                    modeOption={modeOption}
                    onChange={(value) => modeOption && setConfigOption(modeOption.id, value)}
                />
                <ModelSelector
                    modelOption={modelOption}
                    onChange={(value) => modelOption && setConfigOption(modelOption.id, value)}
                />
                <ReasoningEffortSelector
                    thoughtOption={thoughtOption}
                    onChange={(value) => thoughtOption && setConfigOption(thoughtOption.id, value)}
                />
                <div className="ml-auto">
                    {agentBusy ? (
                        <Tooltip title="Stop">
                            <LemonButton
                                type="secondary"
                                status="danger"
                                size="small"
                                icon={<IconStopFilled />}
                                onClick={cancelRun}
                                aria-label="Stop"
                            />
                        </Tooltip>
                    ) : (
                        <Tooltip title={canSend ? 'Send message' : 'Enter a message or attach a file'}>
                            <LemonButton
                                type="primary"
                                size="small"
                                icon={<IconSend />}
                                onClick={() => sendMessage()}
                                loading={sending}
                                disabledReason={sendDisabledReason}
                                aria-label="Send message"
                            />
                        </Tooltip>
                    )}
                </div>
            </div>
        </div>
    )
}
