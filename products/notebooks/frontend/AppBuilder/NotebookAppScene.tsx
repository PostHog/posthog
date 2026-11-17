import { BindLogic, useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { ReactNode, useEffect } from 'react'

import { LemonTabs } from '@posthog/lemon-ui'

import { parseMarkdownNotebook } from 'lib/components/MarkdownNotebook/markdown'
import { notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'

import { NotebookAppBuilder } from './NotebookAppBuilder'
import { notebookAppLogic } from './notebookAppLogic'

export function NotebookAppScene({ shortId, children }: { shortId: string; children: ReactNode }): JSX.Element {
    const { searchParams, hashParams, location } = useValues(router)
    const { saveNotebookNow } = useActions(notebookLogic({ shortId }))
    const { canEditNotebook, isTemplate, markdownEditorValue } = useValues(notebookLogic({ shortId }))
    const { savedNotebook } = useValues(notebookAppLogic({ shortId }))
    const view = searchParams.view === 'builder' ? 'builder' : searchParams.view === 'app' ? 'app' : 'notebook'
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
            <LemonTabs
                activeKey={view}
                onChange={(next) => {
                    saveNotebookNow()
                    router.actions.replace(location.pathname, {
                        ...searchParams,
                        view: next === 'notebook' ? undefined : next,
                    })
                }}
                tabs={[
                    { key: 'notebook', label: 'Notebook' },
                    ...(canEditNotebook && !isTemplate ? [{ key: 'builder', label: 'App builder' }] : []),
                    ...(savedNotebook?.app_published || view === 'app' ? [{ key: 'app', label: 'App' }] : []),
                ]}
            />
            {view === 'notebook' ? children : <NotebookAppBuilder shortId={shortId} published={view === 'app'} />}
        </BindLogic>
    )
}
