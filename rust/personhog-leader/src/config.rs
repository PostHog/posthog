use envconfig::Envconfig;
use std::net::SocketAddr;

#[derive(Envconfig, Clone, Debug)]
pub struct Config {
    #[envconfig(default = "127.0.0.1:50053")]
    pub grpc_address: SocketAddr,

    /// In-memory cache capacity in number of entries
    #[envconfig(default = "100000")]
    pub cache_memory_capacity: usize,

    #[envconfig(default = "9102")]
    pub metrics_port: u16,
}
