const express = require("express");
const { createProvider } = require("./provider");
const { createFlagCache } = require("./flags");
const { renderBanner } = require("./banner");
const analytics = require("./analytics");

const app = express();

const flagCache = createFlagCache(createProvider());

app.get("/api/config", async (req, res) => {
  const promoBanner = await flagCache.getFlag("promo_banner", false);
  const config = {
    promo_banner: promoBanner,
    maintenance_mode: await flagCache.getFlag("maintenance_mode", false),
    new_nav: await flagCache.getFlag("new_nav", false),
  };
  analytics.capture(req.headers["x-client-id"] || "anonymous", "config_served", {
    promo_banner: promoBanner,
  });
  res.set("cache-control", "no-store").json(config);
});

app.get("/api/banner", async (req, res) => {
  const promoBanner = await flagCache.getFlag("promo_banner", false);
  res.type("html").send(renderBanner({ promoBanner }));
});

const port = process.env.PORT || 3000;
if (require.main === module) {
  app.listen(port, () => console.log(`acme-config-service listening on :${port}`));
}

module.exports = app;
