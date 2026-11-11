import type { ReactElement } from 'react'
import { StyleSheet, View } from 'react-native'

import type { EvidenceBlock } from '@/model/types'

import { EvidenceQuotes } from './EvidenceQuotes'
import { EvidenceTrace } from './EvidenceTrace'
import { ReplayRow } from './ReplayRow'

function blockKey(block: EvidenceBlock, index: number): string {
    return `${block.kind}-${index}`
}

interface EvidenceProps {
    blocks: EvidenceBlock[]
    reportId: string
}

export function Evidence({ blocks, reportId }: EvidenceProps): ReactElement | null {
    if (blocks.length === 0) {
        return null
    }
    return (
        <View>
            {blocks.map((block, index) => (
                <View key={blockKey(block, index)} style={index === 0 ? styles.first : styles.next}>
                    {block.kind === 'trace' ? <EvidenceTrace block={block} /> : null}
                    {block.kind === 'quotes' ? <EvidenceQuotes block={block} /> : null}
                    {block.kind === 'replay' ? <ReplayRow block={block} reportId={reportId} /> : null}
                </View>
            ))}
        </View>
    )
}

const styles = StyleSheet.create({
    first: {
        marginTop: 20,
    },
    next: {
        marginTop: 10,
    },
})
