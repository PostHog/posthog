package identity

import (
	"bytes"
	"crypto/rsa"
	"crypto/x509"
	"encoding/json"
	"encoding/pem"
	"errors"
	"io"
	"strings"
)

func validPublicKey(key *rsa.PublicKey) bool {
	return key != nil && key.N != nil && key.N.Sign() > 0 && key.N.BitLen() >= 2048 && key.E >= 3 && key.E%2 != 0
}

func ParseKeyBundle(data []byte) (map[string]*rsa.PublicKey, error) {
	invalid := errors.New("invalid verification key bundle")
	decoder := json.NewDecoder(bytes.NewReader(data))
	if token, err := decoder.Token(); err != nil || token != json.Delim('{') {
		return nil, invalid
	}
	keys := make(map[string]*rsa.PublicKey)
	for decoder.More() {
		token, err := decoder.Token()
		id, ok := token.(string)
		if err != nil || !ok || id == "" || strings.TrimSpace(id) != id || keys[id] != nil {
			return nil, invalid
		}
		var value string
		if err := decoder.Decode(&value); err != nil {
			return nil, invalid
		}
		value = strings.TrimSpace(value)
		block, rest := pem.Decode([]byte(value))
		if block == nil || block.Type != "PUBLIC KEY" || len(block.Headers) != 0 ||
			!strings.HasPrefix(value, "-----BEGIN PUBLIC KEY-----") || len(bytes.TrimSpace(rest)) != 0 {
			return nil, invalid
		}
		parsed, err := x509.ParsePKIXPublicKey(block.Bytes)
		key, ok := parsed.(*rsa.PublicKey)
		if err != nil || !ok || !validPublicKey(key) {
			return nil, invalid
		}
		keys[id] = key
	}
	if token, err := decoder.Token(); err != nil || token != json.Delim('}') || len(keys) == 0 {
		return nil, invalid
	}
	if _, err := decoder.Token(); err != io.EOF {
		return nil, invalid
	}
	return keys, nil
}
