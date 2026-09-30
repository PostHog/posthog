import { LogicWrapper, MakeLogicType, actions, kea, key, path, props, reducers } from 'kea'

import type { NotebookBtwContext } from 'lib/components/MarkdownNotebook/MarkdownNotebook'
import { uuid } from 'lib/utils/dom'

export interface NotebookBtwLogicProps {
    shortId: string
}

export interface NotebookBtwSession {
    panelId: string
    context: NotebookBtwContext
}

export interface notebookBtwLogicValues {
    session: NotebookBtwSession | null
}

export interface notebookBtwLogicActions {
    openBtw: (context: NotebookBtwContext) => { context: NotebookBtwContext; panelId: string }
    closeBtw: () => { value: true }
}

export type notebookBtwLogicType = MakeLogicType<notebookBtwLogicValues, notebookBtwLogicActions, NotebookBtwLogicProps>

export const notebookBtwLogic: LogicWrapper<notebookBtwLogicType> = kea<notebookBtwLogicType>([
    path(['products', 'notebooks', 'frontend', 'notebookBtwLogic']),
    props({} as NotebookBtwLogicProps),
    key(({ shortId }) => shortId),
    actions({
        openBtw: (context: NotebookBtwContext) => ({ context, panelId: `notebook-btw-${uuid()}` }),
        closeBtw: true,
    }),
    reducers({
        session: [
            null as NotebookBtwSession | null,
            {
                openBtw: (_, { context, panelId }) => ({ context, panelId }),
                closeBtw: () => null,
            },
        ],
    }),
])
