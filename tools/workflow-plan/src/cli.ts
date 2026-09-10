import { existsSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { parseArgs } from 'node:util'

import { loadWorkflow, planWorkflow } from './plan.ts'
import { type TableStyle, renderPlanTable, renderSteps } from './render.ts'
import { defaultScenarios } from './scenarios.ts'

const USAGE = `Usage: hogli ci:plan <workflow.yml | workflow name> [--steps <job-id>]

Prints which jobs of the workflow run under each built-in scenario. --steps lists the
steps of one job instead. Every paths filter is stubbed as if all of its filters matched;
outputs that scripts produce are empty, so a matrix built from them cannot be sized here.
The Depot shadow is planned as sampled in (CI_DEPOT_SHADOW_PERCENT set, sample.sampled stubbed to true).`

const WORKFLOWS_DIR = fileURLToPath(new URL('../../../.github/workflows/', import.meta.url))

// pnpm --filter runs this from the package directory; INIT_CWD is where the person typed the command.
function resolveWorkflowPath(argument: string): string {
    const fromInvocation = path.resolve(process.env['INIT_CWD'] ?? process.cwd(), argument)
    if (existsSync(fromInvocation)) {
        return fromInvocation
    }
    const byName = path.join(WORKFLOWS_DIR, argument.endsWith('.yml') ? argument : `${argument}.yml`)
    return existsSync(byName) ? byName : fromInvocation
}

// COLORFGBG is "<fg>;<bg>"; ANSI background 7 or 15 means the terminal is light.
const LIGHT_TERMINAL = /;(7|15)$/

function tableStyle(): TableStyle | undefined {
    if (!process.stdout.isTTY || process.env['NO_COLOR']) {
        return undefined
    }
    const background = LIGHT_TERMINAL.test(process.env['COLORFGBG'] ?? '') ? '\x1b[48;5;254m' : '\x1b[48;5;236m'
    return {
        header: (line) => `\x1b[1m${line}\x1b[0m`,
        stripe: (line) => `${background}${line}\x1b[0m`,
    }
}

function print(text: string): void {
    process.stdout.write(`${text}\n`)
}

function main(argv: string[]): number {
    const { values, positionals } = parseArgs({
        args: argv,
        options: { steps: { type: 'string' }, help: { type: 'boolean' } },
        allowPositionals: true,
    })
    const workflowArgument = positionals[0]
    if (values.help || !workflowArgument) {
        print(USAGE)
        return values.help ? 0 : 2
    }
    const workflow = loadWorkflow(resolveWorkflowPath(workflowArgument))
    const scenarioPlans = defaultScenarios(workflow).map((scenario) => ({
        scenario,
        plan: planWorkflow(workflow, scenario),
    }))
    const style = tableStyle()
    print(`\n${values.steps ? renderSteps(scenarioPlans, values.steps, style) : renderPlanTable(scenarioPlans, style)}`)
    const blocking = scenarioPlans.some(({ plan }) => plan.errors.some((error) => error.where !== 'matrix'))
    return blocking ? 1 : 0
}

process.exitCode = main(process.argv.slice(2))
