import asyncio
import base64
import os
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ["JWT_SECRET"] = "test-only-secret-that-is-not-used-outside-the-test-suite"
os.environ["PAYMENT_PROVIDER"] = "mock"
os.environ["APP_ENV"] = "development"
os.environ["PAYMENT_TOKEN_ENCRYPTION_KEY"] = base64.urlsafe_b64encode(b"x" * 32).decode()
os.environ["DATABASE_URL"] = "postgresql+asyncpg://test:test@localhost/test"

from app.database import get_session
from app.main import create_app
from app.models import Account, Base, Branch, Department, Inventory, Product, Role
from app.security import hash_password


@pytest.fixture
def api(tmp_path: Path):
    database_path = tmp_path / "test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    seeded: dict[str, UUID] = {}

    async def setup() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with sessions() as session:
            admin = Account(
                email="admin@infinity.test",
                password_hash=hash_password("Local-test-admin-password-123"),
                role=Role.ADMIN.value,
            )
            department = Department(code="OPS", name="Operations")
            branch = Branch(
                code="CAI-01",
                name="Cairo Main",
                address_line="1 Test Street",
                city="Cairo",
                country="EG",
            )
            product = Product(
                sku="HW-001",
                name="Test Laptop",
                kind="hardware",
                unit_price="12000.00",
                currency="EGP",
                is_active=True,
            )
            session.add_all([admin, department, branch, product])
            await session.flush()
            stock = Inventory(
                branch_id=branch.id, product_id=product.id, quantity=5, reorder_level=1
            )
            session.add(stock)
            seeded.update(
                {
                    "admin_id": admin.id,
                    "department_id": department.id,
                    "branch_id": branch.id,
                    "product_id": product.id,
                }
            )
            await session.commit()

    asyncio.run(setup())
    asyncio.run(engine.dispose())
    application = create_app()

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with sessions() as session:
            yield session

    application.dependency_overrides[get_session] = override_session
    with TestClient(application) as test_client:
        yield test_client, seeded
    asyncio.run(engine.dispose())
