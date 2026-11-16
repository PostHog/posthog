import type { ProductEmptyStateMode } from 'lib/components/ProductEmptyState/types'

import { MCPHowItWorks } from './MCPHowItWorks'
import { MCPSetupDemoCard } from './MCPSetupDemoCard'

export function MCPSetupSidebar({ mode, preview }: { mode: ProductEmptyStateMode; preview: boolean }): JSX.Element {
    return (
        <div className="flex flex-col gap-4">
            <MCPHowItWorks mode={mode} preview={preview} />
            <MCPSetupDemoCard mode={mode} preview={preview} />
        </div>
    )
}
