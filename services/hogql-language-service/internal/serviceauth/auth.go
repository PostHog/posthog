package serviceauth

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"strings"
	"time"
)

var ErrUnauthorized = errors.New("unauthorized")

// MaxConnectionIDLength bounds the direct-connection segment of a catalog scope. Connection ids
// are UUIDs; the bound keeps a hostile path from minting unbounded registry keys.
const MaxConnectionIDLength = 64

// Authorization is the catalog scope of one request. ConnectionID is empty for the team's PostHog
// catalog, and names a direct warehouse connection otherwise. Two connections of the same user
// hold separate catalogs, so neither can read or overwrite the other.
type Authorization struct {
	TeamID       int64
	UserID       int64
	ConnectionID string
}

func (a Authorization) Valid() bool {
	return a.TeamID > 0 && a.UserID > 0 && validConnectionID(a.ConnectionID)
}

func validConnectionID(connectionID string) bool {
	if len(connectionID) > MaxConnectionIDLength {
		return false
	}
	for _, character := range connectionID {
		switch {
		case character >= 'a' && character <= 'z', character >= 'A' && character <= 'Z':
		case character >= '0' && character <= '9':
		case character == '-', character == '_':
		default:
			return false
		}
	}
	return true
}

type Operation string

const (
	OperationPublish  Operation = "publish"
	OperationDelete   Operation = "delete"
	OperationComplete Operation = "complete"
	OperationValidate Operation = "validate"
)

type Authenticator struct {
	keys          [][]byte
	allowInsecure bool
	now           func() time.Time
}

type header struct {
	Algorithm string `json:"alg"`
}

type Claims struct {
	Audience     string   `json:"aud"`
	TeamID       int64    `json:"team_id"`
	UserID       int64    `json:"user_id"`
	ConnectionID string   `json:"connection_id,omitempty"`
	Operations   []string `json:"operations"`
	ExpiresAt    int64    `json:"exp"`
	NotBefore    int64    `json:"nbf,omitempty"`
}

func New(keys []string, allowInsecure bool) *Authenticator {
	parsed := make([][]byte, 0, len(keys))
	for _, key := range keys {
		if key = strings.TrimSpace(key); key != "" {
			parsed = append(parsed, []byte(key))
		}
	}
	return &Authenticator{keys: parsed, allowInsecure: allowInsecure, now: time.Now}
}

func (a *Authenticator) Verify(headerValue string, authorization Authorization, operation Operation) error {
	if !authorization.Valid() {
		return ErrUnauthorized
	}
	if len(a.keys) == 0 {
		if a.allowInsecure {
			return nil
		}
		return ErrUnauthorized
	}
	if !strings.HasPrefix(headerValue, "Bearer ") {
		return ErrUnauthorized
	}
	parts := strings.Split(strings.TrimPrefix(headerValue, "Bearer "), ".")
	if len(parts) != 3 {
		return ErrUnauthorized
	}
	signed := parts[0] + "." + parts[1]
	signature, err := base64.RawURLEncoding.DecodeString(parts[2])
	if err != nil || !validSignature([]byte(signed), signature, a.keys) {
		return ErrUnauthorized
	}

	var tokenHeader header
	if err := decodePart(parts[0], &tokenHeader); err != nil || tokenHeader.Algorithm != "HS256" {
		return ErrUnauthorized
	}
	var claims Claims
	if err := decodePart(parts[1], &claims); err != nil {
		return ErrUnauthorized
	}
	now := a.now().Unix()
	if claims.Audience != "hogql-language-service" || claims.ExpiresAt <= now || claims.NotBefore > now || claims.TeamID != authorization.TeamID || claims.UserID != authorization.UserID || claims.ConnectionID != authorization.ConnectionID {
		return ErrUnauthorized
	}
	for _, allowed := range claims.Operations {
		if allowed == string(operation) {
			return nil
		}
	}
	return ErrUnauthorized
}

func decodePart(part string, target any) error {
	decoded, err := base64.RawURLEncoding.DecodeString(part)
	if err != nil {
		return err
	}
	return json.Unmarshal(decoded, target)
}

func validSignature(message, signature []byte, keys [][]byte) bool {
	valid := false
	for _, key := range keys {
		mac := hmac.New(sha256.New, key)
		_, _ = mac.Write(message)
		valid = hmac.Equal(signature, mac.Sum(nil)) || valid
	}
	return valid
}
