import express from 'express'

import { initAnalytics } from './analytics.js'
import { createInvoice } from './invoice.js'

const PORT = Number(process.env.PORT ?? 4900)

async function main() {
  await initAnalytics()
  const app = express()
  app.use(express.json())

  app.post('/api/invoices', (req, res) => {
    const { customerId, items, discountCodes = [], region } = req.body ?? {}
    if (!customerId || !Array.isArray(items) || items.length === 0) {
      return res.status(400).json({ error: 'customerId and a non-empty items array are required' })
    }
    const invoice = createInvoice({ customerId, items, region }, discountCodes)
    res.status(201).json(invoice)
  })

  app.listen(PORT, () => {
    console.log(`acme-billing-engine listening on :${PORT}`)
  })
}

main()
