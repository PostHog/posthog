import { useState } from 'react'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { NewInsightMenuContent } from 'scenes/saved-insights/NewInsightMenu'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

/**
 * Create button for the product analytics empty state. It offers the same insight
 * types as the scene's own "New" button, in a modal rather than that button's
 * dropdown - the empty state's action sits mid-scene, where a menu this wide has
 * no room to open against.
 */
export function ProductAnalyticsPrimaryAction(): JSX.Element {
    const [isMenuOpen, setIsMenuOpen] = useState(false)

    return (
        <>
            <AccessControlAction
                resourceType={AccessControlResourceType.Insight}
                minAccessLevel={AccessControlLevel.Editor}
            >
                <LemonButton
                    type="primary"
                    className="self-start"
                    onClick={() => setIsMenuOpen(true)}
                    data-attr="add-insight-button-empty-state"
                >
                    Create your first insight
                </LemonButton>
            </AccessControlAction>
            <LemonModal
                isOpen={isMenuOpen}
                onClose={() => setIsMenuOpen(false)}
                title="Create an insight"
                description="Pick the question you want to answer. You can change the type later."
                width="58rem"
                maxWidth="calc(100vw - 2rem)"
            >
                <NewInsightMenuContent />
            </LemonModal>
        </>
    )
}
