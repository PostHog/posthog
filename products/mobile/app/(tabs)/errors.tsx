import type { ReactElement } from 'react'

import { ErrorsListScreen } from '@/features/errors/ErrorsListScreen'

export default function ErrorsTabRoute(): ReactElement {
    return <ErrorsListScreen chrome="tab" />
}
