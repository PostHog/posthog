import { useActions, useValues } from 'kea'
import { Suspense } from 'react'

import { LemonBanner, LemonButton, LemonModal, Spinner } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { lazyWithRetry } from 'lib/utils/retryImport'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { notebookChangesLogic } from './notebookChangesLogic'

const MonacoDiffEditor = lazyWithRetry(() => import('lib/components/MonacoDiffEditor'))

export function NotebookChangesNotice({
    notebookId,
    markdown,
}: {
    notebookId: string
    markdown: string
}): JSX.Element | null {
    const { user } = useValues(userLogic)
    const { currentTeamId } = useValues(teamLogic)
    const logic = notebookChangesLogic({
        scope: user && currentTeamId ? JSON.stringify([user.id, currentTeamId, notebookId]) : null,
        markdown,
    })
    const { hasChanges, showChanges, previousVisit } = useValues(logic)
    const { setShowChanges, dismissChanges } = useActions(logic)
    if (!hasChanges || !previousVisit) {
        return null
    }
    return (
        <>
            <LemonBanner
                type="info"
                className="mb-4"
                onClose={dismissChanges}
                action={{ children: 'Review changes', onClick: () => setShowChanges(true) }}
            >
                This notebook has changed since your last visit on this browser.
            </LemonBanner>
            <LemonModal
                isOpen={showChanges}
                onClose={() => setShowChanges(false)}
                title="Changes since your last visit"
                width={800}
                footer={
                    <LemonButton type="primary" onClick={() => setShowChanges(false)}>
                        Close
                    </LemonButton>
                }
            >
                <p>
                    Compared with the version you viewed{' '}
                    <TZLabel time={new Date(previousVisit.viewedAt).toISOString()} /> on this browser.
                </p>
                <div className="flex flex-wrap gap-4 mb-3 text-sm">
                    <del className="text-danger bg-danger-highlight">Removed</del>
                    <ins className="text-success bg-success-highlight no-underline">Added</ins>
                </div>
                <div
                    className="max-h-[60vh] overflow-y-auto overflow-x-hidden break-words font-mono text-sm"
                    data-attr="notebook-visit-diff"
                >
                    <Suspense
                        fallback={
                            <div className="flex justify-center my-4">
                                <Spinner className="text-2xl" />
                            </div>
                        }
                    >
                        <MonacoDiffEditor
                            original={previousVisit.markdown}
                            modified={markdown}
                            language="markdown"
                            options={{
                                renderSideBySide: false,
                                renderOverviewRuler: false,
                                renderGutterMenu: false,
                                scrollBeyondLastLine: false,
                                automaticLayout: true,
                                wordWrap: 'on',
                                diffWordWrap: 'on',
                                minimap: { enabled: false },
                                hideUnchangedRegions: {
                                    enabled: true,
                                    contextLineCount: 3,
                                    minimumLineCount: 3,
                                    revealLineCount: 20,
                                },
                            }}
                        />
                    </Suspense>
                </div>
            </LemonModal>
        </>
    )
}
