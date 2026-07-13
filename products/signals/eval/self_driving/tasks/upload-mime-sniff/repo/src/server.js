import { initAnalytics } from './analytics.js'
import { createApp } from './app.js'

const PORT = Number(process.env.PORT ?? 4700)

async function main() {
  await initAnalytics()
  createApp().listen(PORT, () => {
    console.log(`acme-importer listening on :${PORT}`)
  })
}

main()
