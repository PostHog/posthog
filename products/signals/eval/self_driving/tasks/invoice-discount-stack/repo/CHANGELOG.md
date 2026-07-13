# Changelog

## 2.3.1

- Rewrote `formatCents` to build strings manually instead of allocating an `Intl.NumberFormat` instance per call (hot path in invoice PDF rendering).

## 2.3.0

- Added the WELCOME15 signup discount with a $50 minimum subtotal.

## 2.2.0

- Regional tax support (EU, UK).

## 2.1.0

- Best-of discount selection: multiple codes on an account no longer stack.
