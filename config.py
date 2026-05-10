"""
config.py
Central configuration using Pydantic Settings.

Changes in this version:
  - Fixed GeoSettings: Nominatim fields now use correct GEO_ prefix
  - Fixed ModelSettings: LORA_ADAPTER_PATH -> MODEL_LORA_ADAPTER_PATH
  - Added ModelSettings: hf_lora_repo — HF repo for trained LoRA adapter
  - Added HuggingFaceSettings: read/write tokens
  - Added FareSettings: fare model path + optional HF repo
  - Updated AppSettings.summary() to reflect all additions
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).parent.resolve()

 
# DatabaseSettings 

class DatabaseSettings(BaseSettings):
    """
    PostgreSQL direct connection config.
    Tables used: stop, route, route_stop, route_geometry
    Extensions:  pg_trgm, PostGIS, pgRouting
    """

    model_config = SettingsConfigDict(env_prefix="POSTGRES_")

    host:     str = Field(default="localhost")
    port:     int = Field(default=5433)
    db:       str = Field(default="transport_db")
    user:     str = Field(default="postgres")
    password: str = Field(default="postgres")

    @property
    def dsn(self) -> str:
        return (
            f"postgresql://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.db}"
        )

    @property
    def async_dsn(self) -> str:
        return self.dsn.replace("postgresql://", "postgresql+asyncpg://")

    @property
    def psycopg2_params(self) -> dict:
        return {
            "host":     self.host,
            "port":     self.port,
            "dbname":   self.db,
            "user":     self.user,
            "password": self.password,
        }

 
# HuggingFaceSettings   

class HuggingFaceSettings(BaseSettings):
    """
    HuggingFace token config.

    read_token  -> used to:
                    • load Qwen/Qwen2.5-3B-Instruct base model
                    • load your trained LoRA adapter from HF Hub
    write_token -> used to:
                    • push trained LoRA adapter to HF Hub after Colab training
                    • only needed during training, not inference
    """

    model_config = SettingsConfigDict(env_prefix="HF_")

    read_token:  str = Field(default="")
    write_token: str = Field(default="")

    @property
    def has_read_token(self) -> bool:
        return bool(self.read_token and self.read_token != "hf_your_read_token_here")

    @property
    def has_write_token(self) -> bool:
        return bool(self.write_token and self.write_token != "hf_your_write_token_here")

 
# ModelSettings 

class ModelSettings(BaseSettings):
    """
    Intent model configuration (Qwen2.5-3B + LoRA).

    Two adapter sources (priority order):
      1. hf_lora_repo  — load from HuggingFace Hub (post-training)
      2. lora_adapter_path — load from local disk (dev / pre-training)

    Use adapter_source property to decide which to load.
    """

    model_config = SettingsConfigDict(env_prefix="MODEL_")

    name:             str   = Field(default="Qwen/Qwen2.5-3B-Instruct")
    max_new_tokens:   int   = Field(default=256, ge=64,  le=1024)
    temperature:      float = Field(default=0.1, ge=0.0, le=2.0)

    #  LoRA adapter — local path (dev / before training) 
    lora_adapter_path: str = Field(
        default=str(PROJECT_ROOT / "model" / "intent" / "lora_adapter")
    )

    #  LoRA adapter — HF Hub repo (after Colab training) 
    # e.g. "your-hf-username/transport-agent-intent-lora"
    hf_lora_repo: str = Field(default="")

    #  Quantization 
    load_in_4bit:           bool = Field(default=True)
    bnb_4bit_compute_dtype: str  = Field(default="float16")
    bnb_4bit_quant_type:    str  = Field(default="nf4")
    use_nested_quant:       bool = Field(default=True)

    @field_validator("bnb_4bit_compute_dtype")
    @classmethod
    def validate_dtype(cls, v: str) -> str:
        allowed = {"float16", "bfloat16", "float32"}
        if v not in allowed:
            raise ValueError(f"Must be one of {allowed}")
        return v

    @property
    def local_adapter_exists(self) -> bool:
        """True if local LoRA adapter directory has adapter_config.json."""
        p = Path(self.lora_adapter_path)
        return p.exists() and (p / "adapter_config.json").exists()

    @property
    def hf_adapter_configured(self) -> bool:
        """True if an HF repo is set for the LoRA adapter."""
        return bool(self.hf_lora_repo)

    @property
    def adapter_source(self) -> str:
        """
        Returns where to load the adapter from.

        Priority:
          "hf"    -> hf_lora_repo is set (post-training production mode)
          "local" -> local path exists (dev mode)
          "none"  -> no adapter available (base model only)
        """
        if self.hf_adapter_configured:
            return "hf"
        if self.local_adapter_exists:
            return "local"
        return "none"

 
# FareSettings 


class FareSettings(BaseSettings):
    """
    Fare prediction model configuration.

    model_path -> local .pkl file (model/fare/model.pkl)
    hf_repo    -> optional HF Hub repo if fare model was uploaded
                 (leave empty to use local file only)
    """

    model_config = SettingsConfigDict(env_prefix="FARE_")

    model_path: str = Field(
        default=str(PROJECT_ROOT / "model" / "fare" / "model.pkl")
    )
    hf_repo: str = Field(default="")

    @property
    def local_model_exists(self) -> bool:
        return Path(self.model_path).exists()

    @property
    def model_source(self) -> str:
        """
        Returns where to load fare model from.
          "hf"    -> hf_repo is set
          "local" -> local .pkl exists
          "none"  -> not available
        """
        if self.hf_repo:
            return "hf"
        if self.local_model_exists:
            return "local"
        return "none"

 
# GeoSettings  ,Nominatim fields now under GEO_ prefix 

class GeoSettings(BaseSettings):
    """
    Geo-resolution config.
    Uses direct DB access — no external API needed.

    Strategy:
      1. pg_trgm fuzzy search on stop.name / stop.name_ar
      2. PostGIS ST_DWithin nearest stop
      3. Nominatim -> PostGIS (last resort)

    NOTE: All fields use env_prefix="GEO_"
      e.g. GEO_NOMINATIM_URL, GEO_NOMINATIM_TIMEOUT
    """

    model_config = SettingsConfigDict(env_prefix="GEO_")

    similarity_threshold:       float = Field(default=0.3, ge=0.0, le=1.0)
    cache_size:                 int   = Field(default=1000, ge=10)
    nearest_stop_radius_meters: int   = Field(default=800,  ge=50, le=5000)

    #  Nominatim fallback 
    # Env vars: GEO_NOMINATIM_URL, GEO_NOMINATIM_USER_AGENT, GEO_NOMINATIM_TIMEOUT
    nominatim_url:        str = Field(
        default="https://nominatim.openstreetmap.org"
    )
    nominatim_user_agent: str = Field(default="transport-agent-gp/1.0")
    nominatim_timeout:    int = Field(default=10, ge=1, le=60)

 
# RoutingEngineSettings — unchanged logic, kept as-is 

class RoutingEngineSettings(BaseSettings):
    """
    Routing engine API configuration.

    API: https://routing-demo-eval.azurewebsites.net
    Spec: POST /api/routes

    Verified bounds from actual OpenAPI spec:
      max_transfers : integer [0, 5]
      walking_cutoff: integer [100, 5000]
      top_k         : integer [1, 20]
    """

    model_config = SettingsConfigDict(
        env_prefix="ROUTING_",
        populate_by_name=True,
    )

    engine_url: str = Field(
        default="https://routing-demo-eval.azurewebsites.net",
        alias="ROUTING_ENGINE_URL",
    )
    timeout: int = Field(
        default=30, ge=1, le=120,
        alias="ROUTING_ENGINE_TIMEOUT",
    )
    max_transfers: int = Field(
        default=3, ge=0, le=5,
        alias="ROUTING_MAX_TRANSFERS",
    )
    walking_cutoff: int = Field(
        default=1500, ge=100, le=5000,
        alias="ROUTING_WALKING_CUTOFF",
    )
    top_k: int = Field(
        default=10, ge=1, le=20,
        alias="ROUTING_TOP_K",
    )

    max_retries:        int   = Field(default=3,   ge=1, le=10)
    retry_wait_seconds: float = Field(default=1.0, ge=0.1, le=10.0)

    @property
    def routes_url(self) -> str:
        return f"{self.engine_url}/api/routes"

    @property
    def health_url(self) -> str:
        return f"{self.engine_url}/api/health"

    @property
    def admin_responses_url(self) -> str:
        return f"{self.engine_url}/api/admin/responses"

    @property
    def submit_feedback_url(self) -> str:
        return f"{self.engine_url}/api/submit-feedback"

    def clamp_params(
        self,
        max_transfers: int,
        walking_cutoff: int,
        top_k: int,
    ) -> dict:
        return {
            "max_transfers":  max(0,   min(5,    max_transfers)),
            "walking_cutoff": max(100, min(5000, walking_cutoff)),
            "top_k":          max(1,   min(20,   top_k)),
        }

 
# AppSettings  ,UPDATED: added hf + fare sub-settings + updated summary 

class AppSettings(BaseSettings):
    """Root application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    app_env:  Literal["development", "production", "test"] = Field(
        default="development", alias="APP_ENV"
    )
    app_port:  int = Field(default=5000,  alias="APP_PORT")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO", alias="LOG_LEVEL"
    )
    memory_window_size:     int = Field(default=5, ge=1, le=20, alias="MEMORY_WINDOW_SIZE")
    max_displayed_journeys: int = Field(default=3, ge=1, le=10, alias="MAX_DISPLAYED_JOURNEYS")

    #  Sub-settings 
    db:      DatabaseSettings      = Field(default_factory=DatabaseSettings)
    model:   ModelSettings         = Field(default_factory=ModelSettings)
    fare:    FareSettings          = Field(default_factory=FareSettings)       
    hf:      HuggingFaceSettings   = Field(default_factory=HuggingFaceSettings)  
    geo:     GeoSettings           = Field(default_factory=GeoSettings)
    routing: RoutingEngineSettings = Field(default_factory=RoutingEngineSettings)

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def is_test(self) -> bool:
        return self.app_env == "test"

    def summary(self) -> str:
        return (
            f"\n{'='*55}\n"
            f"  TRANSPORT AGENT CONFIG\n"
            f"{'='*55}\n"
            f"  Env:                  {self.app_env}\n"
            f"  Port:                 {self.app_port}\n"
            f"  Log level:            {self.log_level}\n"
            f"\n"
            f"  DB host:              {self.db.host}:{self.db.port}/{self.db.db}\n"
            f"  DB access:            DIRECT (pg_trgm + PostGIS)\n"
            f"\n"
            f"  Routing engine:       {self.routing.engine_url}\n"
            f"  Routes endpoint:      {self.routing.routes_url}\n"
            f"  top_k:                {self.routing.top_k}  (API max: 20)\n"
            f"  max_transfers:        {self.routing.max_transfers}  (API max: 5)\n"
            f"  walking_cutoff:       {self.routing.walking_cutoff}m\n"
            f"\n"
            f"  Intent model:         {self.model.name}\n"
            f"  Adapter source:       {self.model.adapter_source}\n"
            f"  HF LoRA repo:         {self.model.hf_lora_repo or '(not set)'}\n"
            f"\n"
            f"  Fare model source:    {self.fare.model_source}\n"
            f"  Fare model path:      {self.fare.model_path}\n"
            f"  Fare HF repo:         {self.fare.hf_repo or '(not set)'}\n"
            f"\n"
            f"  HF read token:        {'✓ set' if self.hf.has_read_token else '✗ missing'}\n"
            f"  HF write token:       {'✓ set' if self.hf.has_write_token else '✗ missing'}\n"
            f"\n"
            f"  Geo threshold:        {self.geo.similarity_threshold}\n"
            f"  Geo nearest radius:   {self.geo.nearest_stop_radius_meters}m\n"
            f"\n"
            f"  Memory window:        {self.memory_window_size} turns\n"
            f"  Max displayed:        {self.max_displayed_journeys} journeys\n"
            f"{'='*55}"
        )


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    return AppSettings()


settings: AppSettings = get_settings()