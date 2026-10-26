from functools import lru_cache

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "VaultRoute RAG"
    app_version: str = "0.1.0"
    environment: str = "development"
    log_level: str = "INFO"
    host: str = "0.0.0.0"
    port: int = 8000
    database_url: str = "postgresql+asyncpg://vaultroute:vaultroute@localhost:5432/vaultroute"
    qdrant_url: str = "http://localhost:6333"
    dependency_timeout_seconds: float = Field(default=3.0, gt=0, le=30)
    jwt_secret_key: str = "development-only-change-me-before-production"
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "vaultroute-rag"
    jwt_audience: str = "vaultroute-rag-api"
    jwt_access_token_minutes: int = Field(default=30, gt=0, le=1440)
    seed_user_password: str = "ChangeMe123!"
    document_chunk_size_words: int = Field(default=220, ge=80, le=500)
    document_chunk_overlap_words: int = Field(default=40, ge=0, le=100)
    max_upload_bytes: int = Field(default=10 * 1024 * 1024, ge=1024, le=50 * 1024 * 1024)
    embedding_model_name: str = "BAAI/bge-small-en-v1.5"
    embedding_dimension: int = Field(default=384, gt=0, le=4096)
    embedding_cache_dir: str = ".model-cache"
    qdrant_document_collection: str = "document_chunks"
    qdrant_cache_collection: str = "semantic_answer_cache"
    retrieval_candidate_limit: int = Field(default=20, ge=5, le=100)
    retrieval_top_k: int = Field(default=5, ge=1, le=12)
    retrieval_min_score: float = Field(default=0.30, ge=0, le=1)
    answer_min_score: float = Field(default=0.50, ge=0, le=1)
    cache_similarity_threshold: float = Field(default=0.93, ge=0, le=1)
    cache_candidate_limit: int = Field(default=5, ge=1, le=20)
    cache_ttl_seconds: int = Field(default=86400, ge=60, le=2_592_000)
    groq_api_key: SecretStr | None = None
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_model: str = "openai/gpt-oss-20b"
    openai_api_key: SecretStr | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-6-astra"
    model_request_timeout_seconds: float = Field(default=60, gt=0, le=300)
    model_max_output_tokens: int = Field(default=700, ge=100, le=4000)
    groq_input_cost_per_million: float = Field(default=0.075, ge=0)
    groq_output_cost_per_million: float = Field(default=0.30, ge=0)
    openai_input_cost_per_million: float = Field(default=10.0, ge=0)
    openai_output_cost_per_million: float = Field(default=50.0, ge=0)
    allowed_hosts: str = "localhost,127.0.0.1,testserver,api"
    rate_limit_requests_per_minute: int = Field(default=120, ge=10, le=10_000)
    rate_limit_login_per_minute: int = Field(default=10, ge=1, le=1_000)
    rate_limit_query_per_minute: int = Field(default=30, ge=1, le=1_000)
    rate_limit_upload_per_minute: int = Field(default=10, ge=1, le=1_000)
    metrics_bearer_token: SecretStr | None = None
    enable_api_docs: bool = True

    @property
    def allowed_host_list(self) -> list[str]:
        return [host.strip() for host in self.allowed_hosts.split(",") if host.strip()]

    @model_validator(mode="after")
    def validate_production_security(self) -> "Settings":
        if self.environment.lower() != "production":
            return self

        unsafe_secrets = {
            "development-only-change-me-before-production",
            "replace-this-with-a-long-random-secret",
            "replace-with-at-least-32-random-characters",
        }
        if len(self.jwt_secret_key) < 32 or self.jwt_secret_key in unsafe_secrets:
            raise ValueError(
                "Production JWT_SECRET_KEY must be a unique value of at least 32 chars"
            )
        metrics_token = (
            self.metrics_bearer_token.get_secret_value() if self.metrics_bearer_token else ""
        )
        if len(metrics_token) < 24:
            raise ValueError("Production METRICS_BEARER_TOKEN must contain at least 24 chars")
        if metrics_token == "replace-with-at-least-24-random-characters":
            raise ValueError("Production METRICS_BEARER_TOKEN must not use the placeholder")
        if not self.allowed_host_list or "*" in self.allowed_host_list:
            raise ValueError("Production ALLOWED_HOSTS must contain explicit host names")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return one cached settings object for the process."""

    return Settings()
