import { existsSync } from 'node:fs'
import path from 'node:path'
import { parseArgs } from 'node:util'

import { loadWorkflow, planWorkflow } from './plan.ts'
import { type TableStyle, renderPlanTable, renderSteps } from './render.ts'
import { REPO_ROOT, defaultScenarios } from './scenarios.ts'

const USAGE = `Usage: hogli ci:plan <workflow.yml | workflow name> [--steps <job-id>]

Prints which jobs of the workflow run under each built-in scenario. --steps lists the
steps of one job instead. Every paths filter is stubbed as if all of its filters matched;
outputs that scripts produce are empty unless src/scenarios.ts stubs them for the workflow, so an
unstubbed matrix cannot be sized and a gate on one reads as skipped.`

const WORKFLOWS_DIR = path.join(REPO_ROOT, '.github/workflows')

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

// Same shade phrocs uses for a selected row: ANSI black or white follows the terminal theme. Cursor and
// Zed map those to the default background, which would paint nothing, so they get an explicit RGB gray.
function selectionBackground(): string {
    const light = LIGHT_TERMINAL.test(process.env['COLORFGBG'] ?? '')
    const editorTerminal =
        !!process.env['CURSOR_TRACE_ID'] || process.env['TERM_PROGRAM'] === 'zed' || process.env['ZED_TERM'] === 'true'
    if (editorTerminal) {
        return light ? '\x1b[48;2;212;212;212m' : '\x1b[48;2;58;58;58m'
    }
    return light ? '\x1b[47m' : '\x1b[40m'
}

function tableStyle(): TableStyle | undefined {
    if (!process.stdout.isTTY || process.env['NO_COLOR']) {
        return undefined
    }
    const background = selectionBackground()
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
    const workflowPath = resolveWorkflowPath(workflowArgument)
    const workflow = loadWorkflow(workflowPath)
    const scenarioPlans = defaultScenarios(workflow, workflowPath).map((scenario) => ({
        scenario,
        plan: planWorkflow(workflow, scenario),
    }))
    const style = tableStyle()
    print(`\n${values.steps ? renderSteps(scenarioPlans, values.steps, style) : renderPlanTable(scenarioPlans, style)}`)
    return scenarioPlans.some(({ plan }) => plan.errors.length > 0) ? 1 : 0
}

process.exitCode = main(process.argv.slice(2))
