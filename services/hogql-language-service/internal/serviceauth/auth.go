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

type Authorization struct {
	TeamID int64
	UserID int64
}

func (a Authorization) Valid() bool {
	return a.TeamID > 0 && a.UserID > 0
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
	Audience   string   `json:"aud"`
	TeamID     int64    `json:"team_id"`
	UserID     int64    `json:"user_id"`
	Operations []string `json:"operations"`
	ExpiresAt  int64    `json:"exp"`
	NotBefore  int64    `json:"nbf,omitempty"`
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
	if claims.Audience != "hogql-language-service" || claims.ExpiresAt <= now || claims.NotBefore > now || claims.TeamID != authorization.TeamID || claims.UserID != authorization.UserID {
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
