import { BrandMark } from 'lib/components/BrandMark/BrandMark'

import { engineLabel, engineMark } from './utils'

/** The engines' marks in a row, each named on hover, for cells too narrow for the names. */
export const ContentAutopilotEngineMarks = ({ engines }: { engines: string[] }): JSX.Element => (
    <span className="inline-flex items-center gap-1.5 text-secondary">
        {engines.map((engine) => (
            <BrandMark key={engine} name={engineMark(engine)} label={engineLabel(engine)} />
        ))}
    </span>
)
