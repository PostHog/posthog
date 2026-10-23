import type { ReactElement } from 'react'

import { ErrorsListScreen } from '@/features/errors/ErrorsListScreen'

export default function ErrorsRoute(): ReactElement {
    return <ErrorsListScreen chrome="stack" />
}
