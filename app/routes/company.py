from datetime import date
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.dependencies import AdminAccount, CurrentClient, SessionDep, StaffAccount
from app.models import Account, Branch, Client, ClientAddress, Department, Employee, Role
from app.schemas import (
    AddressCreate,
    AddressRead,
    AddressUpdate,
    BranchCreate,
    BranchRead,
    BranchUpdate,
    ClientProfileUpdate,
    ClientRead,
    ClientUpdate,
    DepartmentCreate,
    DepartmentRead,
    DepartmentUpdate,
    EmployeeCreate,
    EmployeeRead,
    EmployeeUpdate,
)
from app.security import hash_password

router = APIRouter(prefix="/api/v1", tags=["Company"])


@router.get("/clients/me", response_model=ClientRead)
async def read_my_profile(client: CurrentClient) -> Client:
    return client


@router.patch("/clients/me", response_model=ClientRead)
async def update_my_profile(
    payload: ClientProfileUpdate, client: CurrentClient, session: SessionDep
) -> Client:
    changes = payload.model_dump(exclude_unset=True)
    email = changes.pop("email", None)
    for key, value in changes.items():
        if value is not None:
            setattr(client, key, value)
    if email is not None:
        client.account.email = str(email).lower()
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Email is already in use") from None
    await session.refresh(client)
    return client


@router.get("/branches", response_model=list[BranchRead])
async def list_public_branches(session: SessionDep) -> list[Branch]:
    return list(
        (
            await session.scalars(
                select(Branch).where(Branch.is_active.is_(True)).order_by(Branch.name)
            )
        ).all()
    )


@router.get("/admin/departments", response_model=list[DepartmentRead])
async def list_departments(_: StaffAccount, session: SessionDep) -> list[Department]:
    return list((await session.scalars(select(Department).order_by(Department.name))).all())


@router.post(
    "/admin/departments",
    response_model=DepartmentRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_department(
    payload: DepartmentCreate, _: AdminAccount, session: SessionDep
) -> Department:
    department = Department(**payload.model_dump())
    session.add(department)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=409, detail="Department code or name already exists"
        ) from None
    await session.refresh(department)
    return department


@router.patch("/admin/departments/{department_id}", response_model=DepartmentRead)
async def update_department(
    department_id: UUID, payload: DepartmentUpdate, _: AdminAccount, session: SessionDep
) -> Department:
    department = await session.get(Department, department_id)
    if department is None:
        raise HTTPException(status_code=404, detail="Department not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(department, key, value)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=409, detail="Department code or name already exists"
        ) from None
    await session.refresh(department)
    return department


@router.delete("/admin/departments/{department_id}", status_code=204)
async def deactivate_department(department_id: UUID, _: AdminAccount, session: SessionDep) -> None:
    department = await session.get(Department, department_id)
    if department is None:
        raise HTTPException(status_code=404, detail="Department not found")
    department.is_active = False
    await session.commit()


@router.get("/admin/branches", response_model=list[BranchRead])
async def list_branches(_: StaffAccount, session: SessionDep) -> list[Branch]:
    return list((await session.scalars(select(Branch).order_by(Branch.name))).all())


@router.post(
    "/admin/branches",
    response_model=BranchRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_branch(payload: BranchCreate, _: AdminAccount, session: SessionDep) -> Branch:
    branch = Branch(**payload.model_dump())
    session.add(branch)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Branch code already exists") from None
    await session.refresh(branch)
    return branch


@router.patch("/admin/branches/{branch_id}", response_model=BranchRead)
async def update_branch(
    branch_id: UUID, payload: BranchUpdate, _: AdminAccount, session: SessionDep
) -> Branch:
    branch = await session.get(Branch, branch_id)
    if branch is None:
        raise HTTPException(status_code=404, detail="Branch not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(branch, key, value)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Branch code already exists") from None
    await session.refresh(branch)
    return branch


@router.delete("/admin/branches/{branch_id}", status_code=204)
async def deactivate_branch(branch_id: UUID, _: AdminAccount, session: SessionDep) -> None:
    branch = await session.get(Branch, branch_id)
    if branch is None:
        raise HTTPException(status_code=404, detail="Branch not found")
    branch.is_active = False
    await session.commit()


@router.get("/admin/employees", response_model=list[EmployeeRead])
async def list_employees(
    _: StaffAccount,
    session: SessionDep,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> list[Employee]:
    return list(
        (
            await session.scalars(
                select(Employee).order_by(Employee.created_at.desc()).offset(offset).limit(limit)
            )
        ).all()
    )


@router.post(
    "/admin/employees",
    response_model=EmployeeRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_employee(
    payload: EmployeeCreate, _: AdminAccount, session: SessionDep
) -> Employee:
    if (
        await session.scalar(select(Department.id).where(Department.id == payload.department_id))
        is None
    ):
        raise HTTPException(status_code=404, detail="Department not found")
    if await session.scalar(select(Branch.id).where(Branch.id == payload.branch_id)) is None:
        raise HTTPException(status_code=404, detail="Branch not found")
    account = Account(
        email=str(payload.email).lower(),
        password_hash=hash_password(payload.password),
        role=Role.EMPLOYEE.value,
    )
    fields = payload.model_dump(exclude={"email", "password"})
    if fields["hired_on"] is None:
        fields["hired_on"] = date.today()
    employee = Employee(account=account, **fields)
    session.add(employee)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=409, detail="Email or employee number already exists"
        ) from None
    await session.refresh(employee)
    return employee


@router.patch("/admin/employees/{employee_id}", response_model=EmployeeRead)
async def update_employee(
    employee_id: UUID, payload: EmployeeUpdate, _: AdminAccount, session: SessionDep
) -> Employee:
    employee = await session.get(Employee, employee_id)
    if employee is None:
        raise HTTPException(status_code=404, detail="Employee not found")
    changes = payload.model_dump(exclude_unset=True)
    email = changes.pop("email", None)
    for relation, model, key in (
        ("department_id", Department, "department_id"),
        ("branch_id", Branch, "branch_id"),
    ):
        if (
            key in changes
            and changes[key] is not None
            and await session.get(model, changes[key]) is None
        ):
            raise HTTPException(
                status_code=404, detail=f"{relation.removesuffix('_id').title()} not found"
            )
    for key, value in changes.items():
        setattr(employee, key, value)
        if key == "is_active":
            account = await session.get(Account, employee.account_id)
            if account:
                account.is_active = value
    if email is not None:
        employee.account.email = str(email).lower()
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Email is already in use") from None
    await session.refresh(employee)
    return employee


@router.delete("/admin/employees/{employee_id}", status_code=204)
async def deactivate_employee(employee_id: UUID, _: AdminAccount, session: SessionDep) -> None:
    employee = await session.get(Employee, employee_id)
    if employee is None:
        raise HTTPException(status_code=404, detail="Employee not found")
    employee.is_active = False
    account = await session.get(Account, employee.account_id)
    if account:
        account.is_active = False
    await session.commit()


@router.get("/admin/clients", response_model=list[ClientRead])
async def list_clients(
    _: StaffAccount,
    session: SessionDep,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> list[Client]:
    return list(
        (
            await session.scalars(
                select(Client).order_by(Client.created_at.desc()).offset(offset).limit(limit)
            )
        ).all()
    )


@router.patch("/admin/clients/{client_id}", response_model=ClientRead)
async def update_client(
    client_id: UUID, payload: ClientUpdate, _: AdminAccount, session: SessionDep
) -> Client:
    client = await session.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    changes = payload.model_dump(exclude_unset=True)
    email = changes.pop("email", None)
    for key, value in changes.items():
        setattr(client, key, value)
        if key == "is_active":
            account = await session.get(Account, client.account_id)
            if account:
                account.is_active = value
    if email is not None:
        client.account.email = str(email).lower()
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Email is already in use") from None
    await session.refresh(client)
    return client


@router.get("/clients/me/addresses", response_model=list[AddressRead])
async def list_my_addresses(client: CurrentClient, session: SessionDep) -> list[ClientAddress]:
    return list(
        (
            await session.scalars(
                select(ClientAddress)
                .where(ClientAddress.client_id == client.id)
                .order_by(ClientAddress.is_default.desc(), ClientAddress.created_at.desc())
            )
        ).all()
    )


@router.post(
    "/clients/me/addresses",
    response_model=AddressRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_my_address(
    payload: AddressCreate, client: CurrentClient, session: SessionDep
) -> ClientAddress:
    # Serialize address-default changes for this client.
    await session.scalar(select(Client).where(Client.id == client.id).with_for_update(of=Client))
    current_default = await session.scalar(
        select(ClientAddress.id).where(
            ClientAddress.client_id == client.id, ClientAddress.is_default.is_(True)
        )
    )
    is_default = payload.is_default or current_default is None
    if is_default:
        await session.execute(
            ClientAddress.__table__.update()
            .where(ClientAddress.client_id == client.id)
            .values(is_default=False)
        )
    address = ClientAddress(
        client_id=client.id,
        **payload.model_dump(exclude={"is_default"}),
        is_default=is_default,
    )
    session.add(address)
    await session.commit()
    await session.refresh(address)
    return address


@router.delete("/clients/me/addresses/{address_id}", status_code=204)
async def delete_my_address(address_id: UUID, client: CurrentClient, session: SessionDep) -> None:
    await session.scalar(select(Client).where(Client.id == client.id).with_for_update(of=Client))
    address = await session.scalar(
        select(ClientAddress).where(
            ClientAddress.id == address_id, ClientAddress.client_id == client.id
        )
    )
    if address is None:
        raise HTTPException(status_code=404, detail="Address not found")
    was_default = address.is_default
    await session.delete(address)
    if was_default:
        replacement = await session.scalar(
            select(ClientAddress)
            .where(ClientAddress.client_id == client.id)
            .order_by(ClientAddress.created_at, ClientAddress.id)
            .limit(1)
        )
        if replacement is not None:
            replacement.is_default = True
    await session.commit()


@router.patch("/clients/me/addresses/{address_id}", response_model=AddressRead)
async def update_my_address(
    address_id: UUID,
    payload: AddressUpdate,
    client: CurrentClient,
    session: SessionDep,
) -> ClientAddress:
    await session.scalar(select(Client).where(Client.id == client.id).with_for_update(of=Client))
    address = await session.scalar(
        select(ClientAddress).where(
            ClientAddress.id == address_id, ClientAddress.client_id == client.id
        )
    )
    if address is None:
        raise HTTPException(status_code=404, detail="Address not found")
    changes = payload.model_dump(exclude_unset=True)
    was_default = address.is_default
    if changes.get("is_default"):
        await session.execute(
            ClientAddress.__table__.update()
            .where(ClientAddress.client_id == client.id)
            .values(is_default=False)
        )
    for key, value in changes.items():
        setattr(address, key, value)
    if was_default and changes.get("is_default") is False:
        replacement = await session.scalar(
            select(ClientAddress)
            .where(
                ClientAddress.client_id == client.id,
                ClientAddress.id != address.id,
            )
            .order_by(ClientAddress.created_at, ClientAddress.id)
            .limit(1)
        )
        if replacement is not None:
            replacement.is_default = True
    await session.commit()
    await session.refresh(address)
    return address
