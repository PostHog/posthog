import { BindLogic, useValues } from 'kea'
import { router } from 'kea-router'
import { ReactNode, useEffect } from 'react'

import { parseMarkdownNotebook } from 'lib/components/MarkdownNotebook/markdown'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'

import { NotebookAppBuilder } from './NotebookAppBuilder'

export function NotebookAppScene({ shortId, children }: { shortId: string; children: ReactNode }): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    return featureFlags[FEATURE_FLAGS.NOTEBOOK_APP_BUILDER] ? (
        <NotebookAppSceneEnabled shortId={shortId}>{children}</NotebookAppSceneEnabled>
    ) : (
        <>{children}</>
    )
}

function NotebookAppSceneEnabled({ shortId, children }: { shortId: string; children: ReactNode }): JSX.Element {
    const { searchParams, hashParams } = useValues(router)
    const { canEditNotebook, isTemplate, markdownEditorValue } = useValues(notebookLogic({ shortId }))
    const view =
        searchParams.view === 'builder' && canEditNotebook && !isTemplate
            ? 'builder'
            : searchParams.view === 'app'
              ? 'app'
              : 'notebook'
    useEffect(() => {
        if (view !== 'notebook' || typeof hashParams.node !== 'string') {
            return
        }
        const source = parseMarkdownNotebook(markdownEditorValue).nodes.find(
            (node) =>
                node.id === hashParams.node || (node.type === 'component' && node.props.nodeId === hashParams.node)
        )
        const selector = `.Notebook [data-markdown-notebook-node-id="${CSS.escape(source?.id ?? hashParams.node)}"]`
        const focusSource = (): boolean => {
            const element = document.querySelector<HTMLElement>(selector)
            if (!element) {
                return false
            }
            element.scrollIntoView({ block: 'center' })
            element.tabIndex = -1
            element.focus({ preventScroll: true })
            return true
        }
        if (focusSource()) {
            return
        }
        const observer = new MutationObserver(() => {
            if (focusSource()) {
                observer.disconnect()
            }
        })
        observer.observe(document.body, { childList: true, subtree: true })
        return () => observer.disconnect()
    }, [view, hashParams.node, markdownEditorValue])
    return (
        <BindLogic logic={notebookLogic} props={{ shortId }}>
            {view === 'notebook' ? children : <NotebookAppBuilder shortId={shortId} published={view === 'app'} />}
        </BindLogic>
    )
}
