from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "LaundryConnect API"
    database_url: str = (
        "postgresql+psycopg://laundry:laundry_dev_password@localhost:5432/laundryconnect"
    )
    # Comma-separated list of allowed frontend origins
    cors_origins: str = "http://localhost:5173"

    # --- Auth (SEC-038) ---
    # No default on purpose: the app refuses to start without a real secret.
    jwt_secret_key: str = Field(min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    # --- Uploaded verification documents (SEC-001, SEC-002) ---
    # Private folder, never served directly; files are only returned through
    # permission-checked API routes.
    upload_dir: str = "uploads"
    max_upload_mb: int = 5

    # --- Orders and delivery (UR-007, UR-008) ---
    delivery_base_fee_cents: int = 3000      # R30 call-out
    delivery_fee_per_km_cents: int = 600     # R6 per km, collection + delivery legs
    max_collection_distance_km: float = 30
    order_min_lead_minutes: int = 60         # earliest collection: 1 hour from now
    order_max_days_ahead: int = 14
    slot_min_minutes: int = 60
    slot_max_minutes: int = 240
    slot_day_start_hour: int = 7             # South African time
    slot_day_end_hour: int = 20

    # --- Drivers and handovers (UR-009, SEC-005 – SEC-008, SEC-022) ---
    driver_share_percent: int = 80           # of the delivery fee; the rest is the platform's
    driver_max_active_jobs: int = 3
    driver_board_default_radius_km: float = 15
    otp_max_attempts: int = 5                # then the code locks; customer makes a new one
    otp_grace_hours: int = 3                 # code stays valid this long after the window ends
    handover_location_tolerance_m: float = 300  # further than this → flagged for review

    # --- Payments (SEC-042) ---
    # "sandbox" simulates a gateway for development. A real provider (PayFast,
    # Yoco, Ozow…) needs a merchant account and its own adapter in
    # app/services/payments.py.
    payment_provider: str = "sandbox"
    # Signs provider notifications. Empty → derived from JWT_SECRET_KEY (dev only).
    payment_webhook_secret: str = ""
    require_payment_before_acceptance: bool = True

    # --- Live tracking (SEC-021, SEC-024) ---
    location_ping_min_seconds: int = 10       # ignore pings more often than this
    tracking_stale_minutes: int = 10          # older positions aren't shown as "live"
    route_deviation_km: float = 2.0           # extra distance allowed off the direct route

    # --- Login protection (SEC-039, SEC-040) ---
    login_max_failures: int = 5
    login_lockout_minutes: int = 15
    mfa_issuer: str = "LaundryConnect"

    # --- Reviews (UR-014) ---
    review_window_days: int = 30

    # --- Address search (geocoding) ---
    # OpenStreetMap Nominatim: free, but max 1 request/second and it asks for an
    # identifying User-Agent – put your project's contact e-mail or website in
    # GEOCODER_USER_AGENT before going live. Swap the URL for a paid provider
    # (or a self-hosted Nominatim) for real traffic.
    geocoder_enabled: bool = True
    geocoder_url: str = "https://nominatim.openstreetmap.org"
    geocoder_user_agent: str = "LaundryConnect/0.1 (development build)"
    geocoder_country_codes: str = "za"
    geocoder_requests_per_minute_per_ip: int = 30

    # --- Per-IP rate limits (SEC-038, SEC-040) ---
    # Counted per client IP. Behind a reverse proxy, start uvicorn with
    # --proxy-headers --forwarded-allow-ips=<proxy IP> so the real IP is used.
    ratelimit_enabled: bool = True
    # Generous per minute: staff on one shop Wi-Fi or a mobile network share an IP
    ratelimit_login_per_minute: int = 20
    ratelimit_login_per_hour: int = 100
    ratelimit_register_per_hour: int = 10
    ratelimit_password_change_per_15_min: int = 10
    ratelimit_reports_per_hour: int = 30

    # --- Backups (SEC-046) ---
    backup_dir: str = "backups"
    # Fernet key that encrypts backups (they hold ID documents and personal data).
    # Make one with:  python -m app.scripts.backup --generate-key
    # Store it somewhere OTHER than the backups (password manager / vault):
    # without it, backups can't be restored.
    backup_encryption_key: str = ""
    backup_keep_days: int = 30
    backup_min_keep: int = 3
    # When pg_dump / pg_restore aren't installed, run them inside this container
    backup_docker_container: str = "laundryconnect-db"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
