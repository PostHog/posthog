import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonButton, LemonInput, LemonModal, LemonTextArea } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { pluralize } from 'lib/utils/strings'

import {
    aeoPromptsBulkImportBodyPromptsItemTopicMax,
    aeoPromptsBulkImportBodyPromptsMax,
} from 'products/web_analytics/frontend/generated/api.zod'

import { contentAutopilotPromptsLogic } from './contentAutopilotPromptsLogic'
import { promptLines } from './utils'

export const ContentAutopilotPromptAddModal = (): JSX.Element => {
    const { addPromptsOpen, addPromptsSubmitting } = useValues(contentAutopilotPromptsLogic)
    const { addPrompts, closeAddPrompts } = useActions(contentAutopilotPromptsLogic)
    const [text, setText] = useState('')
    const [topic, setTopic] = useState('')

    useEffect(() => {
        if (!addPromptsOpen) {
            setText('')
            setTopic('')
        }
    }, [addPromptsOpen])

    const count = promptLines(text).length
    const disabledReason =
        count === 0
            ? 'Enter at least one prompt'
            : count > aeoPromptsBulkImportBodyPromptsMax
              ? `Add up to ${aeoPromptsBulkImportBodyPromptsMax} prompts at a time`
              : undefined

    return (
        <LemonModal
            isOpen={addPromptsOpen}
            onClose={addPromptsSubmitting ? undefined : closeAddPrompts}
            title="Add prompts"
            description="Write each prompt the way a person would ask an AI assistant."
            width={640}
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={closeAddPrompts}
                        disabledReason={addPromptsSubmitting ? 'Wait for the prompts to save' : undefined}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={() => addPrompts(text, topic)}
                        loading={addPromptsSubmitting}
                        disabledReason={disabledReason}
                        data-attr="content-autopilot-prompts-add-submit"
                    >
                        {count > 0 ? `Add ${pluralize(count, 'prompt')}` : 'Add prompts'}
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-4">
                <LemonField.Pure
                    label="Prompts"
                    help="One prompt per line. A prompt that is already tracked gets the topic below."
                >
                    <LemonTextArea
                        value={text}
                        onChange={setText}
                        minRows={6}
                        placeholder="What's the best open source session replay tool?"
                        autoFocus
                        data-attr="content-autopilot-prompts-add-text"
                    />
                </LemonField.Pure>
                <LemonField.Pure label="Topic" help="Optional. Groups the prompts in the overview and the list.">
                    <LemonInput
                        value={topic}
                        onChange={setTopic}
                        maxLength={aeoPromptsBulkImportBodyPromptsItemTopicMax}
                        placeholder="Session replay"
                    />
                </LemonField.Pure>
            </div>
        </LemonModal>
    )
}
