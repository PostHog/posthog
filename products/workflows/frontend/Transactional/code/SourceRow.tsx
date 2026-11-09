import { useActions, useValues } from 'kea'

import { IconCode, IconCopy, IconGithub, IconPlus } from '@posthog/icons'
import { LemonButton, LemonDropdown, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { codeEmailLogic } from './codeEmailLogic'
import { SourceCandidatePicker } from './SourceCandidatePicker'
import { displayRef, parseSourceFile, repoUrl } from './sourceFile'
import { SourceFileForm } from './SourceFileForm'

/** The file in your repository that sends this email, or a way to link it. */
export function SourceRow(): JSX.Element | null {
    const {
        codeEmail,
        codeEmailLoading,
        sourceFormOpen,
        sourcePickerOpen,
        sourceDetectionEnabled,
        canFindInGitHub,
        sourceCandidatesLoading,
    } = useValues(codeEmailLogic)
    const { linkSourceFile, setSourceFormOpen, findSourceCandidates } = useActions(codeEmailLogic)
    const editDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.Workflow,
        AccessControlLevel.Editor
    )
    if (!codeEmail) {
        return null
    }
    const file = codeEmail.source_url ? parseSourceFile(codeEmail.source_url) : null
    const repo = file ? repoUrl(file) : null
    // A link PostHog builds points at HEAD, the default branch, which needs no label.
    const ref = file?.ref === 'HEAD' ? '' : file?.ref
    const detected = sourceDetectionEnabled && !!file && codeEmail.source_origin === 'detected'
    return (
        <LemonDropdown
            visible={sourceFormOpen}
            onClickOutside={() => setSourceFormOpen(false)}
            placement="bottom-start"
            overlay={
                sourcePickerOpen ? (
                    <SourceCandidatePicker />
                ) : (
                    <SourceFileForm
                        initialUrl={codeEmail.source_url}
                        saving={codeEmailLoading}
                        onSave={linkSourceFile}
                    />
                )
            }
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
                            data-attr="code-email-link-source-file"
                        >
                            Link source file
                        </LemonButton>
                        {canFindInGitHub ? (
                            <LemonButton
                                size="xsmall"
                                type="tertiary"
                                icon={<IconGithub />}
                                onClick={findSourceCandidates}
                                disabledReason={
                                    editDisabledReason ?? (sourceCandidatesLoading ? 'Searching GitHub' : undefined)
                                }
                                data-attr="code-email-find-source-in-github"
                            >
                                Find in GitHub
                            </LemonButton>
                        ) : null}
                    </>
                ) : repo ? (
                    <>
                        <Link to={file.url} target="_blank" className="font-mono truncate max-w-full">
                            {file.path}
                        </Link>
                        <span className="whitespace-nowrap">
                            in{' '}
                            <Link to={repo} target="_blank">
                                {file.repo}
                            </Link>
                            {ref ? ',' : ''}
                        </span>
                        {ref ? (
                            <span className="whitespace-nowrap">
                                on <span className="font-mono">{displayRef(ref)}</span>
                            </span>
                        ) : null}
                        {detected ? (
                            <>
                                <Tooltip title="PostHog found this file by searching your GitHub repos for the key.">
                                    <LemonTag type="muted" icon={<IconGithub />}>
                                        Detected from GitHub
                                    </LemonTag>
                                </Tooltip>
                                <LemonButton
                                    size="xsmall"
                                    type="tertiary"
                                    onClick={() => setSourceFormOpen(!sourceFormOpen)}
                                    disabledReason={editDisabledReason ?? undefined}
                                    data-attr="code-email-change-detected-source-file"
                                >
                                    Change
                                </LemonButton>
                            </>
                        ) : null}
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
