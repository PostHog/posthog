package auth

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"regexp"
	"strings"
	"sync"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/posthog/posthog/services/llm-gateway/internal/config"
	"github.com/posthog/posthog/services/llm-gateway/internal/metrics"
)

type User struct {
	UserID         int
	TeamID         *int
	AuthMethod     string
	DistinctID     string
	Scopes         []string
	ApplicationID  *string
	TokenExpiresAt *time.Time
}

type Service struct {
	pool     *pgxpool.Pool
	settings *config.Settings
	cache    *Cache
}

type cacheEntry struct {
	user      *User
	expiresAt time.Time
}

type Cache struct {
	mu      sync.Mutex
	maxSize int
	values  map[string]cacheEntry
}

var bearerPattern = regexp.MustCompile(`(?i)^Bearer\s+(\S+)$`)

func New(pool *pgxpool.Pool, settings *config.Settings) *Service {
	return &Service{pool: pool, settings: settings, cache: &Cache{maxSize: settings.AuthCacheMaxSize, values: map[string]cacheEntry{}}}
}

func ExtractToken(headers map[string][]string) string {
	if values := headers["X-Api-Key"]; len(values) > 0 {
		return strings.TrimSpace(values[0])
	}
	if values := headers["X-API-Key"]; len(values) > 0 {
		return strings.TrimSpace(values[0])
	}
	authHeader := ""
	if values := headers["Authorization"]; len(values) > 0 {
		authHeader = values[0]
	}
	match := bearerPattern.FindStringSubmatch(authHeader)
	if len(match) != 2 {
		return ""
	}
	return strings.TrimSpace(match[1])
}

func (s *Service) Authenticate(ctx context.Context, token string) (*User, error) {
	switch {
	case strings.HasPrefix(token, "phx_"):
		return s.authenticatePersonalKey(ctx, token)
	case strings.HasPrefix(token, "pha_"):
		return s.authenticateOAuthToken(ctx, token)
	default:
		return nil, nil
	}
}

func (s *Service) AuthenticateHeaders(ctx context.Context, headers map[string][]string) (*User, error) {
	token := ExtractToken(headers)
	if token == "" {
		return nil, nil
	}
	return s.Authenticate(ctx, token)
}

func (s *Service) authenticatePersonalKey(ctx context.Context, token string) (*User, error) {
	tokenHash := "sha256$" + sha256Hex(token)
	if hit, user := s.cache.Get(tokenHash); hit {
		metrics.AuthCacheHits.WithLabelValues("personal_api_key").Inc()
		if user == nil {
			metrics.AuthInvalid.WithLabelValues("personal_api_key").Inc()
		}
		return user, nil
	}
	metrics.AuthCacheMisses.WithLabelValues("personal_api_key").Inc()
	var id string
	var userID int
	var scopes []string
	var teamID *int
	var distinctID *string
	err := s.pool.QueryRow(ctx, `
        SELECT pak.id, pak.user_id, pak.scopes, u.current_team_id, u.distinct_id
        FROM posthog_personalapikey pak
        JOIN posthog_user u ON pak.user_id = u.id
        WHERE pak.secure_value = $1 AND u.is_active = true
    `, tokenHash).Scan(&id, &userID, &scopes, &teamID, &distinctID)
	if err != nil {
		s.cache.Set(tokenHash, nil, s.settings.AuthCacheTTL)
		metrics.AuthInvalid.WithLabelValues("personal_api_key").Inc()
		return nil, nil
	}
	if !hasRequiredScope(scopes, false) {
		s.cache.Set(tokenHash, nil, s.settings.AuthCacheTTL)
		metrics.AuthInvalid.WithLabelValues("personal_api_key").Inc()
		return nil, nil
	}
	user := &User{UserID: userID, TeamID: teamID, AuthMethod: "personal_api_key", DistinctID: stringPtrValue(distinctID), Scopes: scopes}
	s.cache.Set(tokenHash, user, s.settings.AuthCacheTTL)
	return user, nil
}

func (s *Service) authenticateOAuthToken(ctx context.Context, token string) (*User, error) {
	tokenHash := sha256Hex(token)
	if hit, user := s.cache.Get(tokenHash); hit {
		metrics.AuthCacheHits.WithLabelValues("oauth_access_token").Inc()
		if user == nil {
			metrics.AuthInvalid.WithLabelValues("oauth_access_token").Inc()
		}
		return user, nil
	}
	metrics.AuthCacheMisses.WithLabelValues("oauth_access_token").Inc()
	var id int
	var userID int
	var scopeRaw *string
	var expires *time.Time
	var applicationID *string
	var teamID *int
	var distinctID *string
	err := s.pool.QueryRow(ctx, `
        SELECT oat.id, oat.user_id, oat.scope, oat.expires, oat.application_id, u.current_team_id, u.distinct_id
        FROM posthog_oauthaccesstoken oat
        JOIN posthog_user u ON oat.user_id = u.id
        WHERE oat.token_checksum = $1 AND u.is_active = true
    `, tokenHash).Scan(&id, &userID, &scopeRaw, &expires, &applicationID, &teamID, &distinctID)
	if err != nil || applicationID == nil || (expires != nil && expires.Before(time.Now().UTC())) {
		s.cache.Set(tokenHash, nil, s.settings.AuthCacheTTLOAuth)
		metrics.AuthInvalid.WithLabelValues("oauth_access_token").Inc()
		return nil, nil
	}
	scopes := []string{}
	if scopeRaw != nil && *scopeRaw != "" {
		scopes = strings.Fields(*scopeRaw)
	}
	if !hasRequiredScope(scopes, true) {
		s.cache.Set(tokenHash, nil, s.settings.AuthCacheTTLOAuth)
		metrics.AuthInvalid.WithLabelValues("oauth_access_token").Inc()
		return nil, nil
	}
	user := &User{UserID: userID, TeamID: teamID, AuthMethod: "oauth_access_token", DistinctID: stringPtrValue(distinctID), Scopes: scopes, ApplicationID: applicationID, TokenExpiresAt: expires}
	s.cache.Set(tokenHash, user, s.settings.AuthCacheTTLOAuth)
	return user, nil
}

func (c *Cache) Get(key string) (bool, *User) {
	c.mu.Lock()
	defer c.mu.Unlock()
	entry, ok := c.values[key]
	if !ok || time.Now().After(entry.expiresAt) {
		delete(c.values, key)
		return false, nil
	}
	if entry.user != nil && entry.user.TokenExpiresAt != nil && time.Now().UTC().After(*entry.user.TokenExpiresAt) {
		delete(c.values, key)
		return false, nil
	}
	return true, entry.user
}

func (c *Cache) Set(key string, user *User, ttl time.Duration) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if len(c.values) >= c.maxSize {
		for k := range c.values {
			delete(c.values, k)
			break
		}
	}
	expiresAt := time.Now().Add(ttl)
	if user != nil && user.TokenExpiresAt != nil && user.TokenExpiresAt.Before(expiresAt) {
		expiresAt = *user.TokenExpiresAt
	}
	c.values[key] = cacheEntry{user: user, expiresAt: expiresAt}
}

func hasRequiredScope(scopes []string, allowWildcard bool) bool {
	for _, scope := range scopes {
		if scope == "llm_gateway:read" || (allowWildcard && scope == "*") {
			return true
		}
	}
	return false
}

func sha256Hex(value string) string {
	sum := sha256.Sum256([]byte(value))
	return hex.EncodeToString(sum[:])
}

func stringPtrValue(value *string) string {
	if value == nil {
		return ""
	}
	return *value
}
