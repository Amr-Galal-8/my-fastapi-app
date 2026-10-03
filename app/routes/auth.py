from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.dependencies import CurrentAccount, SessionDep
from app.models import Account, Client, Role
from app.schemas import ClientRead, ClientRegister, TokenRead
from app.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=ClientRead, status_code=status.HTTP_201_CREATED)
async def register_client(payload: ClientRegister, session: SessionDep) -> Client:
    """Create a client login and profile. Staff accounts are created by an administrator."""
    account = Account(
        email=str(payload.email).lower(),
        password_hash=hash_password(payload.password),
        role=Role.CLIENT.value,
    )
    client = Client(
        account=account,
        first_name=payload.first_name,
        last_name=payload.last_name,
        phone=payload.phone,
    )
    session.add(client)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=409, detail="An account with this email already exists"
        ) from None
    await session.refresh(client)
    return client


@router.post("/token", response_model=TokenRead)
async def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()], session: SessionDep
) -> TokenRead:
    account = await session.scalar(
        select(Account).where(Account.email == form.username.strip().lower())
    )
    if (
        account is None
        or not account.is_active
        or not verify_password(form.password, account.password_hash)
    ):
        raise HTTPException(
            status_code=401,
            detail="Email or password is incorrect",
            headers={"WWW-Authenticate": "Bearer"},
        )
    from app.config import get_settings

    settings = get_settings()
    return TokenRead(
        access_token=create_access_token(account.id, account.role),
        expires_in=settings.access_token_minutes * 60,
    )


@router.get("/me")
async def read_current_account(account: CurrentAccount) -> dict[str, str | bool]:
    return {
        "id": str(account.id),
        "email": account.email,
        "role": account.role,
        "is_active": account.is_active,
    }
