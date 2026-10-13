package serviceauth

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
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
		teamID    int64
		userID    int64
		operation Operation
	}{
		{teamID: 2, userID: 10, operation: OperationComplete},
		{teamID: 1, userID: 20, operation: OperationComplete},
		{teamID: 1, userID: 10, operation: OperationPublish},
	} {
		authorization := Authorization{TeamID: test.teamID, UserID: test.userID}
		if err := authenticator.Verify("Bearer "+token, authorization, test.operation); err == nil {
			t.Fatalf("token unexpectedly authorized %s for team %d user %d", test.operation, test.teamID, test.userID)
		}
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
