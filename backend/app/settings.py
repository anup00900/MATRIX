from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    azure_openai_api_key: str
    azure_openai_endpoint: str = "https://api.core42.ai/"
    azure_openai_api_version: str = "2024-10-21"
    azure_openai_deployment_name: str = "gpt-4.1"
    azure_openai_embedding_deployment: str = "text-embedding-3-large"
    embedding_fallback_model: str = "BAAI/bge-large-en-v1.5"
    storage_root: Path = Path("./storage")
    log_level: str = "INFO"
    host: str = "127.0.0.1"
    port: int = 8000

    @property
    def pdfs_dir(self) -> Path: return self.storage_root / "pdfs"
    @property
    def parsed_dir(self) -> Path: return self.storage_root / "parsed"
    @property
    def wikis_dir(self) -> Path: return self.storage_root / "wikis"
    @property
    def vectors_dir(self) -> Path: return self.storage_root / "vectors"
    @property
    def traces_dir(self) -> Path: return self.storage_root / "traces"
    @property
    def db_path(self) -> Path: return self.storage_root / "db" / "matrix.sqlite"

settings = Settings()
for d in (settings.pdfs_dir, settings.parsed_dir, settings.wikis_dir,
          settings.vectors_dir, settings.traces_dir, settings.db_path.parent):
    d.mkdir(parents=True, exist_ok=True)
