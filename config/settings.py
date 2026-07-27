from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List
from functools import lru_cache


class Settings(BaseSettings):
    # AI
    groq_api_key: str
    anthropic_api_key: str = ""  # optional: enables Claude Haiku fallback on Groq rate limits

    # Telegram
    telegram_bot_token: str
    telegram_chat_id: str

    # Job Search
    search_keywords: str = "Java,Spring Boot,Backend Developer"
    search_location: str = "Brasil"
    search_remote_only: bool = True
    accept_pleno: bool = False
    # Onsite/hybrid postings are still accepted when located in these cities
    # (sudoeste do Paraná, em torno de Dois Vizinhos). Comma-separated,
    # overridable via LOCAL_REGION_CITIES.
    allow_onsite_in_region: bool = True
    local_region_cities: str = (
        "Dois Vizinhos,Francisco Beltrão,Pato Branco,Ampére,Realeza,"
        "Chopinzinho,Coronel Vivida,Itapejara d'Oeste,Salto do Lontra,"
        "São João,Verê,São Jorge d'Oeste,Cruzeiro do Iguaçu,"
        "Nova Prata do Iguaçu,Santo Antônio do Sudoeste,Marmeleiro,"
        "Renascença,Clevelândia,Palmas,Enéas Marques,Capanema,Planalto,"
        "Santa Izabel do Oeste,Vitorino,Mariópolis,Saudade do Iguaçu"
    )
    min_fit_score: int = 60
    min_cv_score: int = 80  # tailored CV only for strong matches (token budget)

    # Per-track geographic policy. Format: "track:regra,track:regra,...".
    # Regras válidas: anywhere (aceita em qualquer país), abroad_only (só
    # fora do Brasil), domestic_only (só no Brasil). Tracks não listados
    # caem em "anywhere" por padrão. Ajuste aqui, sem tocar em código, para
    # refletir a política de quem está rodando esta instância.
    track_rules: str = "dev:anywhere,qa:abroad_only,support:abroad_only"

    # Vagas de ação afirmativa reservadas para PCD são excluídas por padrão.
    # Desligue (false) se você é candidato PCD e quer receber essas vagas.
    exclude_pcd_reserved: bool = True

    # Database
    database_url: str = "sqlite:///./job_hunter.db"

    # Scheduler
    scrape_interval_hours: int = 6

    @property
    def keywords_list(self) -> List[str]:
        return [k.strip() for k in self.search_keywords.split(",")]

    @property
    def local_cities_list(self) -> List[str]:
        return [c.strip() for c in self.local_region_cities.split(",") if c.strip()]

    @property
    def track_rules_dict(self) -> dict[str, str]:
        rules = {}
        for pair in self.track_rules.split(","):
            pair = pair.strip()
            if not pair or ":" not in pair:
                continue
            track, rule = pair.split(":", 1)
            rules[track.strip().lower()] = rule.strip().lower()
        return rules

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache()
def get_settings() -> Settings:
    return Settings()
