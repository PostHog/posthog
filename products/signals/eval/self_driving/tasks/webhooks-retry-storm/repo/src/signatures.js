const crypto = require("crypto");

/** HMAC-SHA256 signature subscribers use to verify payload authenticity. */
function signPayload(secret, body) {
  return crypto.createHmac("sha256", secret).update(body).digest("hex");
}

function verifySignature(secret, body, signature) {
  const expected = signPayload(secret, body);
  return crypto.timingSafeEqual(Buffer.from(expected), Buffer.from(signature));
}

module.exports = { signPayload, verifySignature };
