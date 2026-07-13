const RATES = { us: 599, ca: 799, eu: 999 };

/** Quote shipping in cents. Orders over $75 ship free. */
function quoteShipping(subtotalCents, region = "us") {
  if (subtotalCents >= 7500) return 0;
  return RATES[region] ?? RATES.us;
}

module.exports = { quoteShipping };
