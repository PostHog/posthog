package registry

import (
	"context"
	"errors"
	"fmt"
	"sync/atomic"
	"testing"
	"testing/synctest"
	"time"

	"github.com/PostHog/posthog/products/tasks/services/egress-proxy/internal/identity"
)

var testLookup = identity.LookupRequest{
	TeamID: 42, RunID: "11111111-1111-4111-8111-111111111111", ExecutionID: "22222222-2222-4222-8222-222222222222",
}

func registrationFor(key identity.LookupRequest, expires time.Time) identity.Registration {
	return identity.Registration{
		TeamID: key.TeamID, RunID: key.RunID, ExecutionID: key.ExecutionID,
		ActorID: 7, ActorEpoch: 1, Authority: "run-a.egress.example.com", LeaseExpiresAt: expires,
	}
}

func newTestCache(t *testing.T, lookup identity.Lookup, entries, pending int) *Cache {
	t.Helper()
	cache, err := NewCache(CacheConfig{Lookup: lookup, MaxEntries: entries, MaxConcurrentLookups: pending})
	if err != nil {
		t.Fatal(err)
	}
	return cache
}

func TestCacheOutageDoesNotExtendLease(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		expires := time.Now().Add(30 * time.Second)
		outage := false
		calls := 0
		cache := newTestCache(t, func(_ context.Context, key identity.LookupRequest) (identity.Registration, error) {
			calls++
			if outage {
				return identity.Registration{}, identity.ErrUnavailable
			}
			return registrationFor(key, expires), nil
		}, 2, 1)
		first, err := cache.Lookup(t.Context(), testLookup)
		if err != nil {
			t.Fatal(err)
		}
		outage = true
		for range 20 {
			time.Sleep(time.Second)
			if got, err := cache.Lookup(t.Context(), testLookup); err != nil || got != first {
				t.Fatalf("live lease during outage = %v, %v", got, err)
			}
		}
		time.Sleep(time.Second)
		if _, err := cache.Lookup(t.Context(), testLookup); err != nil {
			t.Fatal(err)
		}
		if calls < 2 {
			t.Fatal("active cache entry never refreshed")
		}
		time.Sleep(5500 * time.Millisecond)
		if _, err := cache.Lookup(t.Context(), testLookup); err != nil {
			t.Fatal(err)
		}
		beforeExpiry := calls
		time.Sleep(500 * time.Millisecond)
		if _, err := cache.Lookup(t.Context(), testLookup); !errors.Is(err, identity.ErrUnavailable) {
			t.Fatalf("expired cache during outage = %v; want unavailable", err)
		}
		if calls != beforeExpiry {
			t.Fatal("lease expiry discarded the failure backoff")
		}
		time.Sleep(500 * time.Millisecond)
		for range 100 {
			if _, err := cache.Lookup(t.Context(), testLookup); !errors.Is(err, identity.ErrUnavailable) {
				t.Fatalf("outage request = %v; want unavailable", err)
			}
		}
		if calls != beforeExpiry+1 {
			t.Fatalf("outage retries = %d; want one", calls-beforeExpiry)
		}
		outage = false
		time.Sleep(time.Second)
		if _, err := cache.Lookup(t.Context(), testLookup); !errors.Is(err, identity.ErrUnauthorized) {
			t.Fatalf("rereading unchanged lease = %v; want unauthorized", err)
		}
		expires = time.Now().Add(30 * time.Second)
		time.Sleep(time.Second)
		if _, err := cache.Lookup(t.Context(), testLookup); err != nil {
			t.Fatalf("worker-renewed lease = %v", err)
		}
	})
}

func TestCacheRefreshRevocation(t *testing.T) {
	for _, cancelRefresh := range []bool{false, true} {
		t.Run(fmt.Sprint(cancelRefresh), func(t *testing.T) {
			synctest.Test(t, func(t *testing.T) {
				ctx, cancel := context.WithCancel(t.Context())
				defer cancel()
				revoked := false
				cache := newTestCache(t, func(_ context.Context, key identity.LookupRequest) (identity.Registration, error) {
					if revoked {
						if cancelRefresh {
							cancel()
						}
						return identity.Registration{}, identity.ErrUnauthorized
					}
					return registrationFor(key, time.Now().Add(30*time.Second)), nil
				}, 2, 1)
				if _, err := cache.Lookup(ctx, testLookup); err != nil {
					t.Fatal(err)
				}
				revoked = true
				time.Sleep(21 * time.Second)
				want := identity.ErrUnauthorized
				if cancelRefresh {
					want = identity.ErrUnavailable
				}
				if _, err := cache.Lookup(ctx, testLookup); !errors.Is(err, want) {
					t.Fatalf("revoked refresh = %v; want %v", err, want)
				}
				if _, err := cache.Lookup(t.Context(), testLookup); !errors.Is(err, identity.ErrUnauthorized) {
					t.Fatalf("revoked execution = %v; want unauthorized", err)
				}
			})
		})
	}
}

func TestCacheScopesAndEviction(t *testing.T) {
	for _, tc := range []struct {
		name string
		err  error
	}{
		{"active", nil},
		{"unavailable", identity.ErrUnavailable},
		{"unauthorized", identity.ErrUnauthorized},
	} {
		t.Run(tc.name, func(t *testing.T) {
			synctest.Test(t, func(t *testing.T) {
				want := tc.err
				calls := map[identity.LookupRequest]int{}
				cache := newTestCache(t, func(_ context.Context, key identity.LookupRequest) (identity.Registration, error) {
					calls[key]++
					return registrationFor(key, time.Now().Add(30*time.Second)), want
				}, 2, 1)
				otherTeam, otherRun, otherExecution := testLookup, testLookup, testLookup
				otherTeam.TeamID++
				otherRun.RunID = "33333333-3333-4333-8333-333333333333"
				otherExecution.ExecutionID = "44444444-4444-4444-8444-444444444444"
				for _, key := range []identity.LookupRequest{testLookup, otherTeam, testLookup, otherRun, testLookup, otherExecution} {
					got, err := cache.Lookup(t.Context(), key)
					if !errors.Is(err, want) {
						t.Fatalf("lookup %v = %v; want %v", key, err, want)
					}
					if err == nil && (got.TeamID != key.TeamID || got.RunID != key.RunID || got.ExecutionID != key.ExecutionID) {
						t.Fatalf("lookup %v = %v", key, got)
					}
				}
				if calls[testLookup] != 1 {
					t.Fatal("recent entry was not cached")
				}
				if _, err := cache.Lookup(t.Context(), otherTeam); !errors.Is(err, want) || calls[otherTeam] != 2 {
					t.Fatalf("evicted entry = %v, lookups = %d; want fresh lookup", err, calls[otherTeam])
				}
				time.Sleep(time.Second)
				wantCalls := 2
				if want != nil {
					wantCalls++
				}
				if _, err := cache.Lookup(t.Context(), otherTeam); !errors.Is(err, want) || calls[otherTeam] != wantCalls {
					t.Fatalf("retry after one second = %v, lookups = %d; want %d", err, calls[otherTeam], wantCalls)
				}
			})
		})
	}
}

func TestCacheRejectsInvalidResults(t *testing.T) {
	for _, tc := range []struct {
		name   string
		mutate func(*identity.Registration)
		want   error
	}{
		{"team", func(r *identity.Registration) { r.TeamID++ }, identity.ErrUnavailable},
		{"run", func(r *identity.Registration) { r.RunID = "other-run" }, identity.ErrUnavailable},
		{"execution", func(r *identity.Registration) { r.ExecutionID = "other-execution" }, identity.ErrUnavailable},
		{"revoked", func(r *identity.Registration) { r.Revoked = true }, identity.ErrUnauthorized},
		{"expired", func(r *identity.Registration) { r.LeaseExpiresAt = time.Now() }, identity.ErrUnauthorized},
		{"oversized lease", func(r *identity.Registration) { r.LeaseExpiresAt = time.Now().Add(time.Hour) }, identity.ErrUnavailable},
	} {
		t.Run(tc.name, func(t *testing.T) {
			cache := newTestCache(t, func(_ context.Context, key identity.LookupRequest) (identity.Registration, error) {
				result := registrationFor(key, time.Now().Add(30*time.Second))
				tc.mutate(&result)
				return result, nil
			}, 1, 1)
			for range 2 {
				if _, err := cache.Lookup(t.Context(), testLookup); !errors.Is(err, tc.want) {
					t.Fatalf("Lookup() = %v; want %v", err, tc.want)
				}
			}
		})
	}
}

func TestCacheClockChanges(t *testing.T) {
	for _, shift := range []time.Duration{-time.Minute, -2 * time.Second, 2 * time.Second, time.Minute} {
		t.Run(shift.String(), func(t *testing.T) {
			synctest.Test(t, func(t *testing.T) {
				expires := time.Now().Add(30 * time.Second)
				outage := false
				cache := newTestCache(t, func(_ context.Context, key identity.LookupRequest) (identity.Registration, error) {
					if outage {
						return identity.Registration{}, identity.ErrUnavailable
					}
					return registrationFor(key, expires), nil
				}, 1, 1)
				if _, err := cache.Lookup(t.Context(), testLookup); err != nil {
					t.Fatal(err)
				}
				outage = true
				clock := cache.clock
				cache.clock = func() clockReading {
					now := clock()
					now.wall = now.wall.Add(shift)
					return now
				}
				time.Sleep(10 * time.Second)
				_, err := cache.Lookup(t.Context(), testLookup)
				if shift > clockMargin || shift < -clockMargin {
					if !errors.Is(err, identity.ErrUnavailable) {
						t.Fatalf("clock jump = %v; want unavailable", err)
					}
				} else if err != nil {
					t.Fatal(err)
				}
				time.Sleep(17 * time.Second)
				if _, err := cache.Lookup(t.Context(), testLookup); err == nil {
					t.Fatal("clock change extended original lease")
				}
			})
		})
	}
}

func TestCacheCoalescesAndBoundsLookups(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		release := make(chan struct{})
		var calls atomic.Int32
		cache := newTestCache(t, func(ctx context.Context, key identity.LookupRequest) (identity.Registration, error) {
			calls.Add(1)
			select {
			case <-ctx.Done():
				return identity.Registration{}, identity.ErrUnavailable
			case <-release:
				return registrationFor(key, time.Now().Add(30*time.Second)), nil
			}
		}, 2, 1)
		results := make(chan error, 16)
		for range cap(results) {
			go func() {
				got, err := cache.Lookup(t.Context(), testLookup)
				if err == nil && got.ExecutionID != testLookup.ExecutionID {
					err = fmt.Errorf("wrong execution: %s", got.ExecutionID)
				}
				results <- err
			}()
		}
		synctest.Wait()
		other := testLookup
		other.TeamID++
		if _, err := cache.Lookup(t.Context(), other); !errors.Is(err, identity.ErrUnavailable) {
			t.Fatalf("lookup capacity exhausted = %v; want unavailable", err)
		}
		ctx, cancel := context.WithCancel(t.Context())
		cancelled := make(chan error, 1)
		go func() {
			_, err := cache.Lookup(ctx, testLookup)
			cancelled <- err
		}()
		synctest.Wait()
		cancel()
		if err := <-cancelled; !errors.Is(err, identity.ErrUnavailable) {
			t.Fatalf("cancelled waiter = %v", err)
		}
		close(release)
		for range cap(results) {
			if err := <-results; err != nil {
				t.Fatal(err)
			}
		}
		if calls.Load() != 1 {
			t.Fatalf("concurrent requests made %d registry calls; want one", calls.Load())
		}
	})
}

func TestCacheExpiryDuringRefresh(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		calls := 0
		cache := newTestCache(t, func(_ context.Context, key identity.LookupRequest) (identity.Registration, error) {
			calls++
			if calls == 1 {
				return registrationFor(key, time.Now().Add(30*time.Second)), nil
			}
			time.Sleep(7 * time.Second)
			return identity.Registration{}, identity.ErrUnavailable
		}, 1, 1)
		if _, err := cache.Lookup(t.Context(), testLookup); err != nil {
			t.Fatal(err)
		}
		time.Sleep(21 * time.Second)
		result := make(chan error, 1)
		go func() {
			_, err := cache.Lookup(t.Context(), testLookup)
			result <- err
		}()
		synctest.Wait()
		if _, err := cache.Lookup(t.Context(), testLookup); err != nil {
			t.Fatalf("live cached lease while refresh pending = %v", err)
		}
		if err := <-result; !errors.Is(err, identity.ErrUnavailable) {
			t.Fatalf("lease expired during failed refresh = %v; want unavailable", err)
		}
	})
}

func TestCacheRejectsCancelledResult(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		calls := 0
		cache := newTestCache(t, func(ctx context.Context, key identity.LookupRequest) (identity.Registration, error) {
			calls++
			if calls > 1 {
				return identity.Registration{}, identity.ErrUnauthorized
			}
			<-ctx.Done()
			return registrationFor(key, time.Now().Add(30*time.Second)), nil
		}, 1, 1)
		ctx, cancel := context.WithTimeout(t.Context(), time.Second)
		defer cancel()
		if _, err := cache.Lookup(ctx, testLookup); !errors.Is(err, identity.ErrUnavailable) {
			t.Fatalf("late result = %v; want unavailable", err)
		}
		time.Sleep(time.Second)
		if _, err := cache.Lookup(t.Context(), testLookup); !errors.Is(err, identity.ErrUnauthorized) {
			t.Fatalf("late result was cached: %v", err)
		}
	})
}

func TestCacheAcceptsRenewalDuringLookup(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		outage := false
		cache := newTestCache(t, func(_ context.Context, key identity.LookupRequest) (identity.Registration, error) {
			if outage {
				return identity.Registration{}, identity.ErrUnavailable
			}
			time.Sleep(5 * time.Second)
			return registrationFor(key, time.Now().Add(30*time.Second)), nil
		}, 1, 1)
		if _, err := cache.Lookup(t.Context(), testLookup); err != nil {
			t.Fatalf("lease renewed during lookup = %v", err)
		}
		outage = true
		time.Sleep(21 * time.Second)
		if _, err := cache.Lookup(t.Context(), testLookup); err != nil {
			t.Fatalf("cached lease within local deadline = %v", err)
		}
		time.Sleep(time.Second)
		if _, err := cache.Lookup(t.Context(), testLookup); !errors.Is(err, identity.ErrUnavailable) {
			t.Fatalf("cache beyond lookup-start deadline = %v; want unavailable", err)
		}
	})
}
