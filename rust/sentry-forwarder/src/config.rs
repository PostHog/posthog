use envconfig::Envconfig;

#[derive(Envconfig, Clone, Debug)]
pub struct Config {
    #[envconfig(from = "BIND_HOST", default = "::")]
    pub host: String,

    #[envconfig(from = "BIND_PORT", default = "8000")]
    pub port: u16,

    #[envconfig(from = "CAPTURE_HOST", default = "http://capture:3000")]
    pub capture_host: String,
}

impl Config {
    pub fn init_with_defaults() -> Result<Self, envconfig::Error> {
        let res = Self::init_from_env()?;
        Ok(res)
    }
}