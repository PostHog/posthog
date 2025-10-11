#!/usr/bin/env tsx

import { execSync } from 'node:child_process'
import * as fs from 'node:fs'

const SCHEMA_URL = 'https://app.posthog.com/api/schema/'
const TEMP_SCHEMA_PATH = 'temp-openapi.yaml'
const OUTPUT_PATH = 'src/api/generated.ts'

async function fetchSchema() {
    try {
        const response = await fetch(SCHEMA_URL)
        if (!response.ok) {
            throw new Error(`Failed to fetch schema: ${response.status} ${response.statusText}`)
        }

        const schema = await response.text()
        fs.writeFileSync(TEMP_SCHEMA_PATH, schema, 'utf-8')

        return true
    } catch (error) {
        console.error('Error fetching schema:', error)
        return false
    }
}

function generateClient() {
    try {
        execSync(`pnpm typed-openapi ${TEMP_SCHEMA_PATH} --output ${OUTPUT_PATH}`, {
            stdio: 'inherit',
        })

        return true
    } catch (error) {
        console.error('Error generating client:', error)
        return false
    }
}

function cleanup() {
    try {
        if (fs.existsSync(TEMP_SCHEMA_PATH)) {
            fs.unlinkSync(TEMP_SCHEMA_PATH)
        }
    } catch (error) {
        console.error('Warning: Could not clean up temporary file:', error)
    }
}

async function main() {
    const schemaFetched = await fetchSchema()
    if (!schemaFetched) {
        process.exit(1)
    }

    const clientGenerated = generateClient()

    cleanup()

    if (!clientGenerated) {
        process.exit(1)
    }
}

main().catch((error) => {
    console.error('Unexpected error:', error)
    process.exit(1)
})
