package serviceauth

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"strings"
	"testing"
	"time"
)

func TestVerifyScopesTokenToCatalogAndOperation(t *testing.T) {
	authenticator := New([]string{"current-key", "previous-key"}, false)
	authenticator.now = func() time.Time { return time.Unix(100, 0) }
	token := signToken(t, "previous-key", Claims{
		Audience:   "hogql-language-service",
		TeamID:     1,
		UserID:     10,
		Operations: []string{"complete"},
		ExpiresAt:  200,
	})

	if err := authenticator.Verify("Bearer "+token, Authorization{TeamID: 1, UserID: 10}, OperationComplete); err != nil {
		t.Fatalf("valid rotated key was rejected: %v", err)
	}
	for _, test := range []struct {
		teamID       int64
		userID       int64
		connectionID string
		operation    Operation
	}{
		{teamID: 2, userID: 10, operation: OperationComplete},
		{teamID: 1, userID: 20, operation: OperationComplete},
		{teamID: 1, userID: 10, operation: OperationPublish},
		{teamID: 1, userID: 10, connectionID: "connection-a", operation: OperationComplete},
	} {
		authorization := Authorization{TeamID: test.teamID, UserID: test.userID, ConnectionID: test.connectionID}
		if err := authenticator.Verify("Bearer "+token, authorization, test.operation); err == nil {
			t.Fatalf("token unexpectedly authorized %s for team %d user %d connection %q", test.operation, test.teamID, test.userID, test.connectionID)
		}
	}
}

func TestVerifyScopesTokenToOneConnection(t *testing.T) {
	authenticator := New([]string{"key"}, false)
	authenticator.now = func() time.Time { return time.Unix(100, 0) }
	token := signToken(t, "key", Claims{
		Audience:     "hogql-language-service",
		TeamID:       1,
		UserID:       10,
		ConnectionID: "connection-a",
		Operations:   []string{"complete"},
		ExpiresAt:    200,
	})

	if err := authenticator.Verify("Bearer "+token, Authorization{TeamID: 1, UserID: 10, ConnectionID: "connection-a"}, OperationComplete); err != nil {
		t.Fatalf("connection token was rejected for its own connection: %v", err)
	}
	for _, connectionID := range []string{"connection-b", ""} {
		authorization := Authorization{TeamID: 1, UserID: 10, ConnectionID: connectionID}
		if err := authenticator.Verify("Bearer "+token, authorization, OperationComplete); err == nil {
			t.Fatalf("connection token authorized connection %q", connectionID)
		}
	}
}

func TestValidRejectsUnusableConnectionIdentifiers(t *testing.T) {
	for _, connectionID := range []string{"../1", "a/b", "a b", strings.Repeat("a", MaxConnectionIDLength+1)} {
		if (Authorization{TeamID: 1, UserID: 10, ConnectionID: connectionID}).Valid() {
			t.Fatalf("connection id %q was accepted", connectionID)
		}
	}
	if !(Authorization{TeamID: 1, UserID: 10, ConnectionID: "01923f4b-7b2c-7000-8000-a1b2c3d4e5f6"}).Valid() {
		t.Fatal("a UUID connection id was rejected")
	}
}

func TestVerifyRejectsExpiredAndUnsignedTokens(t *testing.T) {
	authenticator := New([]string{"key"}, false)
	authenticator.now = func() time.Time { return time.Unix(100, 0) }
	expired := signToken(t, "key", Claims{Audience: "hogql-language-service", TeamID: 1, UserID: 10, Operations: []string{"complete"}, ExpiresAt: 100})

	for _, authorization := range []string{"", "Bearer unsigned", "Bearer " + expired} {
		if err := authenticator.Verify(authorization, Authorization{TeamID: 1, UserID: 10}, OperationComplete); err == nil {
			t.Fatalf("invalid token was accepted: %q", authorization)
		}
	}
	if err := New(nil, true).Verify("", Authorization{}, OperationComplete); err == nil {
		t.Fatal("insecure local mode accepted an empty authorization scope")
	}
}

func signToken(t *testing.T, key string, claims Claims) string {
	t.Helper()
	headerJSON, err := json.Marshal(header{Algorithm: "HS256"})
	if err != nil {
		t.Fatal(err)
	}
	claimsJSON, err := json.Marshal(claims)
	if err != nil {
		t.Fatal(err)
	}
	encodedHeader := base64.RawURLEncoding.EncodeToString(headerJSON)
	encodedClaims := base64.RawURLEncoding.EncodeToString(claimsJSON)
	message := encodedHeader + "." + encodedClaims
	mac := hmac.New(sha256.New, []byte(key))
	_, _ = mac.Write([]byte(message))
	return message + "." + base64.RawURLEncoding.EncodeToString(mac.Sum(nil))
}
