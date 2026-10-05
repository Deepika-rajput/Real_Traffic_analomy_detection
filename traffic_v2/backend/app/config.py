"""All settings come from environment variables (see backend/README.md). Safe defaults for dev."""
import os
import secrets
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _bool(name, default=False):
    v = os.environ.get(name)
    return default if v is None else v.strip().lower() in ("1", "true", "yes", "on")


class Settings:
    def __init__(self):
        e = os.environ.get
        self.data_dir = Path(e("DATA_DIR", str(PROJECT_ROOT / "backend_data"))).resolve()
        self.db_path = self.data_dir / "traffic.db"
        self.clips_dir = self.data_dir / "clips"
        self.snap_dir = self.data_dir / "snapshots"
        self.uploads_dir = self.data_dir / "uploads"
        self.outbox_dir = self.data_dir / "outbox"

        # detector
        self.weights = e("WEIGHTS", str(PROJECT_ROOT / "temporal.pth"))
        self.mock_detector = _bool("MOCK_DETECTOR")          # fake detector for UI dev / tests
        self.mock_script = e("MOCK_SCRIPT", "accident:5-10")  # label:start_s-end_s,...

        # training-data feedback loop
        self.train_videos_dir = Path(e("TRAIN_VIDEOS_DIR", str(PROJECT_ROOT / "videos")))

        # security
        self.api_key = e("API_KEY")                          # unset = open (dev only)
        self.cors_origins = [o.strip() for o in e(
            "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000").split(",")]
        self.public_base_url = e("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
        self.max_upload_mb = int(e("MAX_UPLOAD_MB", "500"))

        # clip recording
        self.pre_roll_s = float(e("PRE_ROLL_S", "8"))
        self.post_roll_s = float(e("POST_ROLL_S", "6"))
        self.max_clip_s = float(e("MAX_CLIP_S", "90"))
        self.clip_fps = float(e("CLIP_FPS", "12"))
        self.clip_max_width = int(e("CLIP_MAX_WIDTH", "854"))
        self.cooldown_s = float(e("COOLDOWN_S", "90"))        # repeat of same alert within this = duplicate

        # severity tiers (peak probability)
        self.high_prob = float(e("HIGH_PROB", "0.90"))
        self.med_prob = float(e("MED_PROB", "0.75"))

        # alerts
        self.send_mode = e("SEND_MODE", "dry_run")           # dry_run | smtp
        self.test_recipient = e("TEST_RECIPIENT")            # if set, EVERY email goes here instead
        self.smtp_host = e("SMTP_HOST")
        self.smtp_port = int(e("SMTP_PORT", "587"))
        self.smtp_user = e("SMTP_USER")
        self.smtp_pass = e("SMTP_PASS")
        self.smtp_tls = _bool("SMTP_TLS", True)
        self.mail_from = e("MAIL_FROM", "traffic-alerts@localhost")
        self.max_radius_km = float(e("MAX_RADIUS_KM", "50"))
        self.ack_timeout_min = float(e("ACK_TIMEOUT_MIN", "10"))
        # which authority types to notify per event type
        self.authority_types = {
            "accident": ["police", "hospital"],
            "sudden_stop": ["traffic_control"],
            "congestion": ["traffic_control"],
        }

    def ensure_dirs(self):
        for d in (self.data_dir, self.clips_dir, self.snap_dir, self.uploads_dir, self.outbox_dir):
            d.mkdir(parents=True, exist_ok=True)

    @property
    def secret_key(self):
        """Used to sign evidence links. From SECRET_KEY, else generated once and stored."""
        s = os.environ.get("SECRET_KEY")
        if s:
            return s
        f = self.data_dir / ".secret"
        if not f.exists():
            self.ensure_dirs()
            f.write_text(secrets.token_hex(32))
        return f.read_text().strip()


settings = Settings()
