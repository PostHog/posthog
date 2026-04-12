import type { ReactElement } from 'react'

import { Tooltip } from '@posthog/mosaic'

import { RolloutBar } from './RolloutBar'

export interface Variant {
    key: string
    name?: string
    rollout_percentage: number
}

export interface VariantTableProps {
    variants: Variant[]
}

export function VariantTable({ variants }: VariantTableProps): ReactElement {
    return (
        <div className="overflow-hidden rounded-md border border-border-primary">
            <table className="w-full text-sm">
                <thead>
                    <tr className="bg-bg-secondary text-left text-text-secondary">
                        <th className="px-3 py-2 font-medium">Key</th>
                        <th className="px-3 py-2 font-medium">Name</th>
                        <th className="px-3 py-2 font-medium w-1/3">
                            <Tooltip content="Traffic distribution among variants" position="bottom">
                                <span className="cursor-default border-b border-dashed border-text-secondary">
                                    Rollout
                                </span>
                            </Tooltip>
                        </th>
                    </tr>
                </thead>
                <tbody>
                    {variants.map((v) => (
                        <tr key={v.key} className="border-t border-border-primary">
                            <td className="px-3 py-2 font-mono text-xs">{v.key}</td>
                            <td className="px-3 py-2 text-text-secondary">{v.name || '\u2014'}</td>
                            <td className="px-3 py-2">
                                <RolloutBar percentage={v.rollout_percentage} />
                            </td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    )
}
