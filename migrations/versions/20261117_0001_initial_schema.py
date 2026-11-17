"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-11-17 10:21:15.986507+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "administrators",
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_administrators")),
        sa.UniqueConstraint("email", name=op.f("uq_administrators_email")),
    )
    op.create_table(
        "projects",
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("recipient_email", sa.String(length=320), nullable=False),
        sa.Column("sender_name", sa.String(length=100), nullable=True),
        sa.Column("sender_email", sa.String(length=320), nullable=True),
        sa.Column(
            "allowed_origins",
            postgresql.ARRAY(sa.String(length=255)),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "allowed_recipient_domains",
            postgresql.ARRAY(sa.String(length=255)),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "contact_enabled", sa.Boolean(), server_default="true", nullable=False
        ),
        sa.Column(
            "transactional_enabled",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
        sa.Column(
            "notifications_enabled", sa.Boolean(), server_default="true", nullable=False
        ),
        sa.Column(
            "acknowledgement_enabled",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
        sa.Column(
            "turnstile_enabled", sa.Boolean(), server_default="false", nullable=False
        ),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("rate_limit", sa.Integer(), server_default="60", nullable=False),
        sa.Column("daily_quota", sa.Integer(), server_default="500", nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "daily_quota > 0", name=op.f("ck_projects_daily_quota_positive")
        ),
        sa.CheckConstraint(
            "rate_limit > 0", name=op.f("ck_projects_rate_limit_positive")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_projects")),
        sa.UniqueConstraint("slug", name=op.f("uq_projects_slug")),
    )
    op.create_table(
        "api_keys",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("key_prefix", sa.String(length=32), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_api_keys_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_keys")),
        sa.UniqueConstraint("key_hash", name=op.f("uq_api_keys_key_hash")),
    )
    op.create_index(
        op.f("ix_api_keys_project_id"), "api_keys", ["project_id"], unique=False
    )
    op.create_table(
        "contact_submissions",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("sender_name", sa.String(length=100), nullable=False),
        sa.Column("sender_email", sa.String(length=320), nullable=False),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "status", sa.String(length=32), server_default="received", nullable=False
        ),
        sa.Column("resend_message_id", sa.String(length=100), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_contact_submissions_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contact_submissions")),
    )
    op.create_index(
        "ix_contact_submissions_project_id_created_at",
        "contact_submissions",
        ["project_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "email_logs",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("recipient", sa.String(length=320), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("email_type", sa.String(length=32), nullable=False),
        sa.Column(
            "provider", sa.String(length=32), server_default="resend", nullable=False
        ),
        sa.Column("resend_message_id", sa.String(length=100), nullable=True),
        sa.Column(
            "status", sa.String(length=32), server_default="pending", nullable=False
        ),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_email_logs_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_email_logs")),
        sa.UniqueConstraint(
            "resend_message_id", name=op.f("uq_email_logs_resend_message_id")
        ),
    )
    op.create_index(
        "ix_email_logs_project_id_created_at",
        "email_logs",
        ["project_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_email_logs_status"), "email_logs", ["status"], unique=False
    )
    op.create_table(
        "email_events",
        sa.Column("email_log_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("provider_event_id", sa.String(length=255), nullable=False),
        sa.Column(
            "event_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["email_log_id"],
            ["email_logs.id"],
            name=op.f("fk_email_events_email_log_id_email_logs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_email_events")),
        sa.UniqueConstraint(
            "provider_event_id", name=op.f("uq_email_events_provider_event_id")
        ),
    )
    op.create_index(
        op.f("ix_email_events_email_log_id"),
        "email_events",
        ["email_log_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_email_events_email_log_id"), table_name="email_events")
    op.drop_table("email_events")
    op.drop_index(op.f("ix_email_logs_status"), table_name="email_logs")
    op.drop_index("ix_email_logs_project_id_created_at", table_name="email_logs")
    op.drop_table("email_logs")
    op.drop_index(
        "ix_contact_submissions_project_id_created_at", table_name="contact_submissions"
    )
    op.drop_table("contact_submissions")
    op.drop_index(op.f("ix_api_keys_project_id"), table_name="api_keys")
    op.drop_table("api_keys")
    op.drop_table("projects")
    op.drop_table("administrators")
