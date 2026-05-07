import type { ReactElement } from 'react'

import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@posthog/quill'

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
        <div className="overflow-hidden rounded-md border">
            <table className="w-full text-sm">
                <thead>
                    <tr className="bg-muted/50 text-left text-muted-foreground">
                        <th className="px-3 py-2 font-medium">Key</th>
                        <th className="px-3 py-2 font-medium">Name</th>
                        <th className="px-3 py-2 font-medium w-1/3">
                            <TooltipProvider>
                                <Tooltip>
                                    <TooltipTrigger
                                        render={
                                            <span className="cursor-default border-b border-dashed border-muted-foreground">
                                                Rollout
                                            </span>
                                        }
                                    />
                                    <TooltipContent side="bottom">Traffic distribution among variants</TooltipContent>
                                </Tooltip>
                            </TooltipProvider>
                        </th>
                    </tr>
                </thead>
                <tbody>
                    {variants.map((v) => (
                        <tr key={v.key} className="border-t">
                            <td className="px-3 py-2 font-mono text-xs">{v.key}</td>
                            <td className="px-3 py-2 text-muted-foreground">{v.name || '\u2014'}</td>
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
