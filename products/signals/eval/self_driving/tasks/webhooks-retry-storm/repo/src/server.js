const express = require("express");
const crypto = require("crypto");
const { enqueue, pendingCount } = require("./queue");
const analytics = require("./analytics");

const app = express();
app.use(express.json());

const endpoints = new Map();

app.post("/api/endpoints", (req, res) => {
  const { url, events = [] } = req.body;
  if (!url) return res.status(400).json({ error: "url_required" });
  const id = `ep_${crypto.randomBytes(4).toString("hex")}`;
  const secret = crypto.randomBytes(16).toString("hex");
  endpoints.set(id, { id, url, events, secret });
  res.status(201).json({ id, secret });
});

app.get("/api/endpoints", (req, res) => {
  res.json({ endpoints: [...endpoints.values()].map(({ secret, ...rest }) => rest) });
});

app.post("/api/events", (req, res) => {
  const { type, data } = req.body;
  if (!type) return res.status(400).json({ error: "type_required" });
  const event = {
    id: `evt_${crypto.randomBytes(6).toString("hex")}`,
    type,
    data,
    createdAt: new Date().toISOString(),
  };
  let fanout = 0;
  for (const endpoint of endpoints.values()) {
    if (endpoint.events.length === 0 || endpoint.events.includes(type)) {
      enqueue(endpoint, event);
      fanout += 1;
    }
  }
  analytics.capture("system", "webhook_event_received", { type, fanout, queue_depth: pendingCount() });
  res.status(202).json({ eventId: event.id, fanout });
});

const port = process.env.PORT || 3000;
if (require.main === module) {
  app.listen(port, () => console.log(`acme-webhooks listening on :${port}`));
}

module.exports = app;
