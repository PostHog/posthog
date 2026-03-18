import { useActions, useValues } from 'kea'

import { IconCopy } from '@posthog/icons'
import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { WorkflowTemplateLogicProps, workflowTemplateLogic } from './workflowTemplateLogic'

export function TemplateJsonModal(props: WorkflowTemplateLogicProps = {}): JSX.Element {
    const logic = workflowTemplateLogic(props)
    const { templateJsonModalVisible, templateJson } = useValues(logic)
    const { hideTemplateJsonModal } = useActions(logic)

    return (
        <LemonModal
            onClose={hideTemplateJsonModal}
            isOpen={templateJsonModalVisible}
            title="Template JSON"
            width="60vw"
            footer={
                <LemonButton type="secondary" onClick={hideTemplateJsonModal}>
                    Close
                </LemonButton>
            }
        >
            <div className="space-y-4">
                <div className="p-3 bg-primary-highlight rounded border">
                    Copy your template and create or edit the template file in the posthog repository under{' '}
                    <code className="text-xs">products/workflows/backend/templates</code>
                </div>
                <div className="relative">
                    <div className="absolute top-2 right-2 z-10">
                        <LemonButton
                            icon={<IconCopy />}
                            size="small"
                            onClick={() => copyToClipboard(templateJson, 'template JSON')}
                        >
                            Copy
                        </LemonButton>
                    </div>
                    <CodeEditorResizeable
                        language="json"
                        value={templateJson}
                        height={500}
                        options={{
                            readOnly: true,
                            minimap: { enabled: false },
                        }}
                    />
                </div>
            </div>
        </LemonModal>
    )
}
