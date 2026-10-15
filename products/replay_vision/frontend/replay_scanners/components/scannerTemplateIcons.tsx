import { IconCheckCircle, IconNotebook, IconTarget, IconThumbsDown, IconWarning } from '@posthog/icons'

import { ScannerTemplateIcon } from '../scannerTemplates'

export const SCANNER_TEMPLATE_ICONS: Record<ScannerTemplateIcon, JSX.Element> = {
    warning: <IconWarning />,
    notebook: <IconNotebook />,
    target: <IconTarget />,
    'thumbs-down': <IconThumbsDown />,
    check: <IconCheckCircle />,
}
