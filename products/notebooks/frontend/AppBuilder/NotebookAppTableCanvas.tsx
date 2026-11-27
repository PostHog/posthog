import { BindLogic } from 'kea'
import { type ComponentProps, useId } from 'react'

import { NotebookAppCanvas } from './NotebookAppCanvas'
import { notebookAppTableDraftsLogic } from './notebookAppTableDraftsLogic'

export function NotebookAppTableCanvas(props: ComponentProps<typeof NotebookAppCanvas>): JSX.Element {
    return (
        <BindLogic logic={notebookAppTableDraftsLogic} props={{ sessionId: useId() }}>
            <NotebookAppCanvas {...props} />
        </BindLogic>
    )
}
