import { BrandMark } from 'lib/components/BrandMark/BrandMark'

import { engineLabel, engineMark } from './utils'

export const ContentAutopilotEngineLabel = ({ engine }: { engine: string }): JSX.Element => (
    <span className="inline-flex min-w-0 max-w-full items-center gap-1.5 whitespace-nowrap">
        <BrandMark name={engineMark(engine)} />
        <span className="truncate">{engineLabel(engine)}</span>
    </span>
)
