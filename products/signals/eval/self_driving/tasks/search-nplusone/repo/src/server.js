import express from 'express'

import { initAnalytics } from './analytics.js'
import { registerRoutes } from './routes.js'
import { DirectoryStore } from './store.js'

const PORT = Number(process.env.PORT ?? 4600)

async function main() {
  await initAnalytics()
  const app = express()
  app.use(express.json())
  registerRoutes(app, new DirectoryStore())
  app.listen(PORT, () => {
    console.log(`acme-directory listening on :${PORT}`)
  })
}

main()
