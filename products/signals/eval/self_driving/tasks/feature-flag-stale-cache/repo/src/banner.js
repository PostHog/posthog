/** Render the promo banner fragment served to the storefront. */
function renderBanner({ promoBanner }) {
  if (!promoBanner) return "";
  return '<aside class="promo-banner">Summer sale: 20% off sitewide with code SUN20</aside>';
}

module.exports = { renderBanner };
