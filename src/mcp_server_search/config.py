from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    """
    Application settings.
    """
    cache_file_path: str = 'cache/google_cache.db'
    request_delay: int = 5
    max_retries: int = 3
    num_results: int = 5
    use_cache: bool = True
    include_descriptions: bool = True

    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8')

settings = Settings()