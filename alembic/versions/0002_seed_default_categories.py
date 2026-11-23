"""seed_default_categories

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-21 21:47:52.353654

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_CATEGORIES: list[dict[str, str]] = [
    {"code": "FOOD", "name": "Ăn uống"},
    {"code": "TRANSPORT", "name": "Di chuyển"},
    {"code": "ACCOMMODATION", "name": "Lưu trú"},
    {"code": "UTILITIES", "name": "Hóa đơn & Tiện ích"},
    {"code": "ENTERTAINMENT", "name": "Giải trí"},
]


def upgrade() -> None:
    categories_table = sa.table(
        "categories",
        sa.column("code", sa.String),
        sa.column("name", sa.String),
    )
    op.bulk_insert(categories_table, DEFAULT_CATEGORIES)


def downgrade() -> None:
    codes = [item["code"] for item in DEFAULT_CATEGORIES]
    categories_table = sa.table("categories", sa.column("code", sa.String))
    op.execute(categories_table.delete().where(categories_table.c.code.in_(codes)))
