from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    desc,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql.elements import conv

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class Wallet(Base):
    __tablename__ = "wallets"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_wallets_user_id"),
        CheckConstraint("balance >= 0.00", name="balance_non_negative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_wallets_user", ondelete="RESTRICT"),
        nullable=False,
    )
    balance: Mapped[Decimal] = mapped_column(
        Numeric(15, 2),
        nullable=False,
        default=Decimal("0.00"),
        server_default=text("0.00"),
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="VND",
        server_default=text("'VND'"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    user: Mapped[User] = relationship("User", back_populates="wallet")
    ledger_transactions: Mapped[list[LedgerTransaction]] = relationship(
        "LedgerTransaction",
        back_populates="wallet",
    )


class LedgerTransaction(Base):
    """Bảng sổ cái bất biến (chỉ INSERT, tuyệt đối không UPDATE/DELETE)."""

    __tablename__ = "ledger_transactions"
    __table_args__ = (
        # Dùng conv() để giữ đúng tên rút gọn chk_ledger_* như đặc tả schema
        # thay vì bị naming_convention ghép thành chk_ledger_transactions_*.
        CheckConstraint(
            "transaction_type IN ('DEPOSIT', 'SETTLEMENT_OUT', 'SETTLEMENT_IN')",
            name=conv("chk_ledger_type"),
        ),
        CheckConstraint("amount > 0.00", name=conv("chk_ledger_amount_positive")),
        CheckConstraint(
            "balance_before >= 0.00 AND balance_after >= 0.00",
            name=conv("chk_ledger_balances_non_negative"),
        ),
        Index("idx_ledger_wallet_created", "wallet_id", desc("created_at")),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    wallet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("wallets.id", name="fk_ledger_wallet", ondelete="RESTRICT"),
        nullable=False,
    )
    transaction_type: Mapped[str] = mapped_column(String(30), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    balance_before: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    balance_after: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    reference_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reference_note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    wallet: Mapped[Wallet] = relationship("Wallet", back_populates="ledger_transactions")