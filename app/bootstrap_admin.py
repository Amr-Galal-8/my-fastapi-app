import asyncio

from sqlalchemy import select

from app.config import get_settings
from app.database import SessionFactory, engine
from app.models import Account, Role
from app.security import hash_password


async def main() -> None:
    settings = get_settings()
    if not settings.bootstrap_admin_email or not settings.bootstrap_admin_password:
        raise SystemExit(
            "Set BOOTSTRAP_ADMIN_EMAIL and BOOTSTRAP_ADMIN_PASSWORD in your local .env first."
        )
    async with SessionFactory() as session:
        existing = await session.scalar(
            select(Account).where(Account.email == settings.bootstrap_admin_email.lower())
        )
        if existing:
            raise SystemExit("An account with this email already exists.")
        session.add(
            Account(
                email=settings.bootstrap_admin_email.lower(),
                password_hash=hash_password(settings.bootstrap_admin_password.get_secret_value()),
                role=Role.ADMIN.value,
            )
        )
        await session.commit()
    print("Administrator account created.")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
