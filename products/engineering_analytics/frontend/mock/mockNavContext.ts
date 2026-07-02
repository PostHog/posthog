/** Mock navigation context in its own module so vite HMR of the page/component files never
 *  re-creates the context object (which would silently disconnect consumers from the provider). */

import { createContext } from 'react'

export type MockRoute =
    | { page: 'repo' }
    | { page: 'workflow'; slug: string }
    | { page: 'run'; id: number }
    | { page: 'pr'; number: number }
    | { page: 'author'; handle: string }
    // the unvalued lens: "pr: any" / "author: any" — the full list is the filter with no value picked
    | { page: 'prList' }
    | { page: 'authorList' }

export const MockNavContext = createContext<{ route: MockRoute; go: (r: MockRoute) => void }>({
    route: { page: 'repo' },
    go: () => {},
})
