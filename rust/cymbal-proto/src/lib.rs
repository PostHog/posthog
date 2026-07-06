pub mod cymbal {
    pub mod resolution {
        pub mod v1 {
            tonic::include_proto!("cymbal.resolution.v1");

            impl ErrorKind {
                /// Bounded metric label for this error kind, shared by the
                /// remote client and the resolution service so their `kind=`
                /// labels never drift.
                pub fn metric_label(self) -> &'static str {
                    match self {
                        ErrorKind::Unspecified => "unspecified",
                        ErrorKind::InvalidPayload => "invalid_payload",
                        ErrorKind::Poison => "poison",
                        ErrorKind::Unhandled => "unhandled",
                        ErrorKind::Overloaded => "overloaded",
                    }
                }
            }
        }
    }
}
