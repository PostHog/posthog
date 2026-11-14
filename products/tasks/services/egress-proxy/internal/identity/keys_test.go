package identity_test

import (
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/rsa"
	"crypto/x509"
	"encoding/json"
	"encoding/pem"
	"testing"

	"github.com/PostHog/posthog/products/tasks/services/egress-proxy/internal/identity"
)

func publicKeyPEM(t *testing.T, key any) string {
	t.Helper()
	der, err := x509.MarshalPKIXPublicKey(key)
	if err != nil {
		t.Fatal(err)
	}
	return string(pem.EncodeToMemory(&pem.Block{Type: "PUBLIC KEY", Bytes: der}))
}

func keyBundle(t *testing.T, keys map[string]string) []byte {
	t.Helper()
	data, err := json.Marshal(keys)
	if err != nil {
		t.Fatal(err)
	}
	return data
}

func TestParseKeyBundle(t *testing.T) {
	key := signingKey(t)
	encoded := publicKeyPEM(t, &key.PublicKey)
	private := string(pem.EncodeToMemory(&pem.Block{Type: "RSA PRIVATE KEY", Bytes: x509.MarshalPKCS1PrivateKey(key)}))
	ecKey, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	weakKey := &rsa.PublicKey{N: key.N, E: 4}
	value, err := json.Marshal(encoded)
	if err != nil {
		t.Fatal(err)
	}
	for _, tc := range []struct {
		name string
		data []byte
	}{
		{name: "empty bundle", data: []byte(`{}`)},
		{name: "null bundle", data: []byte(`null`)},
		{name: "array bundle", data: []byte(`[]`)},
		{name: "invalid JSON", data: []byte(`{"current":`)},
		{name: "trailing object", data: append(keyBundle(t, map[string]string{"current": encoded}), []byte(`{}`)...)},
		{name: "duplicate key ID", data: []byte(`{"current":` + string(value) + `,"current":` + string(value) + `}`)},
		{name: "empty key ID", data: keyBundle(t, map[string]string{"": encoded})},
		{name: "padded key ID", data: keyBundle(t, map[string]string{" current": encoded})},
		{name: "non-string key", data: []byte(`{"current":42}`)},
		{name: "private key", data: keyBundle(t, map[string]string{"current": private})},
		{name: "second PEM block", data: keyBundle(t, map[string]string{"current": encoded + private})},
		{name: "prefix before PEM", data: keyBundle(t, map[string]string{"current": "unexpected\n" + encoded})},
		{name: "non-RSA key", data: keyBundle(t, map[string]string{"current": publicKeyPEM(t, &ecKey.PublicKey)})},
		{name: "invalid exponent", data: keyBundle(t, map[string]string{"current": publicKeyPEM(t, weakKey)})},
		{name: "malformed PEM", data: keyBundle(t, map[string]string{"current": "-----BEGIN PUBLIC KEY-----\ninvalid\n-----END PUBLIC KEY-----"})},
	} {
		t.Run(tc.name, func(t *testing.T) {
			keys, err := identity.ParseKeyBundle(tc.data)
			if err == nil || keys != nil {
				t.Fatalf("ParseKeyBundle() = %v, %v; want invalid bundle rejected", keys, err)
			}
		})
	}
	keys, err := identity.ParseKeyBundle(keyBundle(t, map[string]string{"current": encoded}))
	if err != nil || len(keys) != 1 || !key.PublicKey.Equal(keys["current"]) {
		t.Fatalf("ParseKeyBundle() = %v, %v; want configured public key", keys, err)
	}
}
