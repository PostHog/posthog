pub mod config;
pub mod kafka;
pub mod metrics;

// Re-export main modules for library users
pub use config::Config;
pub use kafka::KafkaMonitor;