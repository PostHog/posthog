/** Perform a single HTTP delivery to a subscriber endpoint. */
async function deliverToEndpoint(endpoint, payload) {
  const response = await fetch(endpoint.url, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-acme-signature": payload.signature,
    },
    body: payload.body,
  });
  return { status: response.status };
}

module.exports = { deliverToEndpoint };
