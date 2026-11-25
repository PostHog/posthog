//! Local IPC for hosts with a separate workspace process.
#![cfg(unix)]
pub mod broker;
pub mod client;
pub mod socket;
