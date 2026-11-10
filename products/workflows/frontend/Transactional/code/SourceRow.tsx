import { useActions, useValues } from 'kea'

import { IconCode, IconCopy, IconPlus } from '@posthog/icons'
import { LemonButton, LemonDropdown, Link } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { codeEmailLogic } from './codeEmailLogic'
import { parseSourceFile, repoUrl } from './sourceFile'
import { SourceFileForm } from './SourceFileForm'

/** The file in your repository that sends this email, or a way to link it. */
export function SourceRow(): JSX.Element | null {
    const { codeEmail, saving, sourceFormOpen, editDisabledReason } = useValues(codeEmailLogic)
    const { linkSourceFile, setSourceFormOpen } = useActions(codeEmailLogic)
    if (!codeEmail) {
        return null
    }
    const file = codeEmail.source_url ? parseSourceFile(codeEmail.source_url) : null
    const repo = file ? repoUrl(file) : null
    return (
        <LemonDropdown
            visible={sourceFormOpen && !editDisabledReason}
            onClickOutside={() => setSourceFormOpen(false)}
            placement="bottom-start"
            overlay={<SourceFileForm initialUrl={codeEmail.source_url} saving={saving} onSave={linkSourceFile} />}
        >
            <div className="flex flex-wrap items-center gap-1 text-secondary min-w-0" data-attr="code-email-source-row">
                <IconCode className="shrink-0" />
                {!file ? (
                    <>
                        <span>No source file linked yet.</span>
                        <LemonButton
                            size="xsmall"
                            type="tertiary"
                            icon={<IconPlus />}
                            onClick={() => setSourceFormOpen(!sourceFormOpen)}
                            disabledReason={editDisabledReason ?? undefined}
                            data-attr="code-email-link-source-file"
                        >
                            Link source file
                        </LemonButton>
                    </>
                ) : repo ? (
                    <>
                        <Link to={file.url} target="_blank" className="font-mono truncate max-w-full" title={file.url}>
                            {file.path.split('/').pop()}
                        </Link>
                        <span className="truncate max-w-full" title={file.repo}>
                            in{' '}
                            <Link to={repo} target="_blank">
                                {file.repo}
                            </Link>
                        </span>
                    </>
                ) : (
                    <span className="flex items-center gap-1 min-w-0">
                        <span className="font-mono truncate">{file.path}</span>
                        <LemonButton
                            size="xsmall"
                            icon={<IconCopy />}
                            tooltip="Copy the link"
                            onClick={() => void copyToClipboard(file.url, 'link')}
                        />
                    </span>
                )}
            </div>
        </LemonDropdown>
    )
}
