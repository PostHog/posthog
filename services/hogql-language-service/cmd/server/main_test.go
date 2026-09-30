package main

import "testing"

func TestInsecureAuthenticationRequiresExplicitLoopbackOptIn(t *testing.T) {
	for _, test := range []struct {
		address    string
		configured string
		allowed    bool
		wantError  bool
	}{
		{address: "127.0.0.1:8091", configured: "", allowed: false},
		{address: "127.0.0.1:8091", configured: "1", allowed: true},
		{address: "0.0.0.0:8091", configured: "1", allowed: false, wantError: true},
	} {
		allowed, err := allowInsecureAuthentication(test.address, test.configured)
		if allowed != test.allowed || (err != nil) != test.wantError {
			t.Fatalf("address %q configured %q returned allowed=%t error=%v", test.address, test.configured, allowed, err)
		}
	}
}
