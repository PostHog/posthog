pub mod personhog {
    pub mod types {
        pub mod v1 {
            tonic::include_proto!("personhog.types.v1");

            impl LifecycleOpType {
                /// The `lifecycle_op.op_type` value this variant mirrors —
                /// also what the writer projects into the person tables'
                /// `fencing_op_type` column.
                pub const fn as_op_type_str(self) -> &'static str {
                    match self {
                        LifecycleOpType::Delete => "delete",
                        LifecycleOpType::Merge => "merge",
                        LifecycleOpType::Unspecified => "unspecified",
                    }
                }

                /// Inverse of [`as_op_type_str`]; unknown values map to
                /// `Unspecified` (fail-open on the label only, never on the
                /// fence itself — a fence's presence is its `op_id`).
                ///
                /// [`as_op_type_str`]: LifecycleOpType::as_op_type_str
                pub fn from_op_type_str(op_type: &str) -> Self {
                    match op_type {
                        "delete" => LifecycleOpType::Delete,
                        "merge" => LifecycleOpType::Merge,
                        _ => LifecycleOpType::Unspecified,
                    }
                }
            }
        }
    }
    pub mod identity {
        pub mod v1 {
            tonic::include_proto!("personhog.identity.v1");
        }
    }
    pub mod lifecycle {
        pub mod v1 {
            tonic::include_proto!("personhog.lifecycle.v1");
        }
    }
    pub mod leader {
        pub mod v1 {
            tonic::include_proto!("personhog.leader.v1");
        }
    }
    pub mod replica {
        pub mod v1 {
            tonic::include_proto!("personhog.replica.v1");
        }
    }
    pub mod service {
        pub mod v1 {
            tonic::include_proto!("personhog.service.v1");
        }
    }
}
