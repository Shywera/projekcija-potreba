from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Samostalni Nabava app - vlastiti SQLite. Za Postgres postavi DATABASE_URL u .env.
    database_url: str = "sqlite:///./nabava.db"


settings = Settings()
