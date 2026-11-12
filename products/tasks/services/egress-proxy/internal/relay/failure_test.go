package relay

import (
	"context"
	"crypto/tls"
	"errors"
	"io"
	"net"
	"net/url"
	"syscall"
	"testing"
)

func TestClassifyFailure(t *testing.T) {
	for _, tc := range []struct {
		name string
		err  error
		want FailureKind
	}{
		{"canceled", context.Canceled, FailureCanceled},
		{"certificate", &tls.CertificateVerificationError{Err: errors.New("synthetic certificate detail")}, FailureTLS},
		{"DNS", &net.DNSError{Name: "private.example.com", Err: "synthetic DNS detail"}, FailureDNS},
		{"DNS timeout", &net.DNSError{Name: "private.example.com", IsTimeout: true}, FailureDNS},
		{"deadline", context.DeadlineExceeded, FailureTimeout},
		{"dial timeout", &net.OpError{Op: "dial", Err: context.DeadlineExceeded}, FailureTimeout},
		{"connect", &net.OpError{Op: "dial", Err: syscall.ECONNREFUSED}, FailureConnect},
		{"read", &net.OpError{Op: "read", Err: syscall.ECONNRESET}, FailureOther},
		{"lost response", io.EOF, FailureOther},
	} {
		t.Run(tc.name, func(t *testing.T) {
			err := &url.Error{Op: "Get", URL: "https://private.example.com/?token=synthetic", Err: tc.err}
			if got := classifyFailure(err); got != tc.want {
				t.Fatalf("failure kind = %q, want %q", got, tc.want)
			}
		})
	}
}
