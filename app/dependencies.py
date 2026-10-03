from collections.abc import Callable
from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import Account, Client, Role
from app.security import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")
SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_current_account(
    token: Annotated[str, Depends(oauth2_scheme)], session: SessionDep
) -> Account:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired access token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_access_token(token)
        account_id = UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise credentials_error from None

    account = await session.get(Account, account_id)
    if account is None or not account.is_active or account.role != payload.get("role"):
        raise credentials_error
    return account


def require_roles(*allowed_roles: Role) -> Callable:
    async def dependency(account: Annotated[Account, Depends(get_current_account)]) -> Account:
        if account.role not in {role.value for role in allowed_roles}:
            raise HTTPException(status_code=403, detail="You do not have permission to do this")
        return account

    return dependency


async def get_current_client(
    account: Annotated[Account, Depends(require_roles(Role.CLIENT))], session: SessionDep
) -> Client:
    client = await session.scalar(select(Client).where(Client.account_id == account.id))
    if client is None or not client.is_active:
        raise HTTPException(status_code=403, detail="Client account is inactive")
    return client


CurrentAccount = Annotated[Account, Depends(get_current_account)]
CurrentClient = Annotated[Client, Depends(get_current_client)]
AdminAccount = Annotated[Account, Depends(require_roles(Role.ADMIN))]
StaffAccount = Annotated[Account, Depends(require_roles(Role.ADMIN, Role.EMPLOYEE))]
