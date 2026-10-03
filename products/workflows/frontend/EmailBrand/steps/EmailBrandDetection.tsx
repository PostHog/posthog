import { useActions, useValues } from 'kea'

import { IconCheck } from '@posthog/icons'
import { LemonButton, LemonCard, LemonTag, Spinner } from '@posthog/lemon-ui'

import { emailBrandFlowLogic } from '../emailBrandFlowLogic'
import type { EmailBrandFlowProps } from '../emailBrandFlowLogic'
import { EmailBrandPreview } from '../EmailBrandPreview'

export function EmailBrandDetection(props: EmailBrandFlowProps): JSX.Element {
    const logic = emailBrandFlowLogic(props)
    const { step, detection, visibleFiles, draft, logoUrl, preview } = useValues(logic)
    const { reviewDetection } = useActions(logic)
    if (step === 'detecting') {
        return (
            <div className="py-12 text-center">
                <Spinner className="text-3xl" />
                <h2 className="mt-4">Reading your app's brand files</h2>
                <p className="text-secondary">
                    Looking for your name, theme colors, font and logo. This usually takes a few seconds.
                </p>
            </div>
        )
    }
    return (
        <div className="grid grid-cols-1 @min-[48rem]:grid-cols-2 gap-6 py-4">
            <div className="min-w-0 space-y-4">
                <h2>Your brand, from your code</h2>
                <p className="break-words text-secondary">{detection?.repository}</p>
                <LemonCard hoverEffect={false} className="p-4 space-y-3">
                    {detection?.files_read.slice(0, visibleFiles).map((file) => (
                        <div key={file.path} className="min-w-0">
                            <div className="flex gap-2 items-center">
                                <IconCheck className="text-success shrink-0" />
                                <span className="break-all text-sm">{file.path}</span>
                            </div>
                            <div className="flex flex-wrap gap-1 mt-1">
                                {file.found.length ? (
                                    file.found.map((found) => (
                                        <LemonTag key={`${found.field}-${found.value}`}>
                                            <span className="break-all">{`${found.field.replaceAll('_', ' ')}: ${found.value}`}</span>
                                        </LemonTag>
                                    ))
                                ) : (
                                    <span className="text-secondary text-xs">No brand signals in this file</span>
                                )}
                            </div>
                        </div>
                    ))}
                    {visibleFiles < (detection?.files_read.length ?? 0) && <Spinner />}
                    {!detection?.files_read.length && (
                        <p className="mb-0 text-secondary">No brand files found. You can fill in your brand by hand.</p>
                    )}
                </LemonCard>
                <LemonButton type="primary" fullWidth center onClick={reviewDetection} data-attr="email-brand-review">
                    Review my brand
                </LemonButton>
            </div>
            <EmailBrandPreview draft={draft} logoUrl={logoUrl} starter={preview} />
        </div>
    )
}
