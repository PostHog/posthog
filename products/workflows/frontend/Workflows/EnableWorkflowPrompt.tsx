import { LemonButton, LemonModal } from '@posthog/lemon-ui'

const domainList = new Intl.ListFormat('en', { type: 'conjunction' })

export interface EnableWorkflowPromptProps {
    domains: string[] | null
    onConfirm: () => void
    onCancel: () => void
    loading?: boolean
}

export function EnableWorkflowPrompt({
    domains,
    onConfirm,
    onCancel,
    loading,
}: EnableWorkflowPromptProps): JSX.Element {
    const several = (domains?.length ?? 0) > 1
    return (
        <LemonModal
            isOpen={!!domains}
            onClose={onCancel}
            title="Enable this workflow?"
            width={480}
            footer={
                <>
                    <LemonButton type="secondary" onClick={onCancel} data-attr="workflow-enable-prompt-cancel">
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={onConfirm}
                        loading={loading}
                        data-attr="workflow-enable-prompt-confirm"
                    >
                        Enable
                    </LemonButton>
                </>
            }
        >
            <p className="mb-0">
                <strong className="break-all">{domainList.format(domains ?? [])}</strong>{' '}
                {several ? "aren't verified yet" : "isn't verified yet"}. The workflow turns on now and starts sending
                once {several ? 'these domains are' : 'the domain is'} verified.
            </p>
        </LemonModal>
    )
}
