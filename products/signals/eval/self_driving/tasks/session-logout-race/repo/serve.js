import path from 'node:path'
import { fileURLToPath } from 'node:url'

import express from 'express'

const root = path.dirname(fileURLToPath(import.meta.url))
const PORT = Number(process.env.PORT ?? 4800)

const app = express()
app.use(express.static(path.join(root, 'public')))
app.use('/src', express.static(path.join(root, 'src')))

app.listen(PORT, () => {
  console.log(`acme-portal listening on :${PORT}`)
})
