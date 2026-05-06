"""Seed the mcp-dev-summit PostgreSQL database with sample data.

Usage:
    uv run python scripts/seed_db.py

Reads POSTGRES_URL from env or .env file.
Default: postgresql://postgres:PASSWORD_REDACTED@postgres-eo.eastus.cloudapp.azure.com:5432/mcp-dev-summit

Idempotent — safe to run multiple times (uses IF NOT EXISTS / ON CONFLICT).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

POSTGRES_URL_DEFAULT = (
    "postgresql://postgres:PASSWORD_REDACTED@postgres-eo.eastus.cloudapp.azure.com:5432/mcp-dev-summit"
)

SEED_SQL = """\
-- Customers
CREATE TABLE IF NOT EXISTS customers (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    plan VARCHAR(50) DEFAULT 'free',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Support tickets
CREATE TABLE IF NOT EXISTS support_tickets (
    id SERIAL PRIMARY KEY,
    customer_id INTEGER REFERENCES customers(id),
    subject VARCHAR(255) NOT NULL,
    status VARCHAR(20) DEFAULT 'open',
    priority VARCHAR(10) DEFAULT 'medium',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Invoices
CREATE TABLE IF NOT EXISTS invoices (
    id SERIAL PRIMARY KEY,
    customer_id INTEGER REFERENCES customers(id),
    amount_cents INTEGER NOT NULL,
    currency VARCHAR(3) DEFAULT 'USD',
    status VARCHAR(20) DEFAULT 'pending',
    issued_at TIMESTAMPTZ DEFAULT NOW(),
    paid_at TIMESTAMPTZ
);

-- Sample customers
INSERT INTO customers (name, email, plan) VALUES
    ('Alice Corp', 'alice@example.com', 'enterprise'),
    ('Bob Startup', 'bob@example.com', 'pro'),
    ('Carol Dev', 'carol@example.com', 'free')
ON CONFLICT (email) DO NOTHING;

-- Sample tickets
INSERT INTO support_tickets (customer_id, subject, status, priority) VALUES
    (1, 'Cannot access dashboard', 'open', 'high'),
    (1, 'Billing question', 'closed', 'low'),
    (2, 'API rate limit issue', 'open', 'medium'),
    (3, 'Feature request: dark mode', 'open', 'low')
ON CONFLICT DO NOTHING;

-- Sample invoices
INSERT INTO invoices (customer_id, amount_cents, currency, status) VALUES
    (1, 99900, 'USD', 'paid'),
    (2, 4900, 'USD', 'paid'),
    (3, 0, 'USD', 'paid'),
    (1, 99900, 'USD', 'pending')
ON CONFLICT DO NOTHING;
"""


def _load_dotenv_postgres_url() -> str | None:
    """Try to read POSTGRES_URL from a .env file in the project root."""
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if not env_file.exists():
        return None
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() == "POSTGRES_URL":
            return value.strip().strip('"').strip("'")
    return None


def get_postgres_url() -> str:
    """Resolve the database URL from env, .env file, or default."""
    url = os.environ.get("POSTGRES_URL")
    if url:
        return url
    url = _load_dotenv_postgres_url()
    if url:
        return url
    return POSTGRES_URL_DEFAULT


def main() -> int:
    """Seed the database. Returns 0 on success, 1 on failure."""
    url = get_postgres_url()

    db_name = url.rsplit("/", 1)[-1] if "/" in url else "unknown"
    host = url.split("@")[-1].split("/")[0] if "@" in url else "unknown"
    print(f"Seeding database: {db_name} on {host}")

    try:
        result = subprocess.run(
            ["psql", url],
            input=SEED_SQL,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError:
        print("ERROR: psql not found. Install PostgreSQL client tools.")
        print("  macOS:  brew install postgresql")
        print("  Ubuntu: sudo apt install postgresql-client")
        return 1
    except subprocess.TimeoutExpired:
        print("ERROR: psql timed out after 30s. Check network/credentials.")
        return 1

    if result.returncode != 0:
        print(f"ERROR: psql exited with code {result.returncode}")
        if result.stderr:
            print(result.stderr.strip())
        return 1

    print("Tables created and sample data inserted.")

    # Print summary
    summary = subprocess.run(
        [
            "psql",
            url,
            "-c",
            "SELECT 'customers: ' || count(*) FROM customers "
            "UNION ALL SELECT 'support_tickets: ' || count(*) FROM support_tickets "
            "UNION ALL SELECT 'invoices: ' || count(*) FROM invoices;",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if summary.returncode == 0:
        print(summary.stdout.strip())

    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
