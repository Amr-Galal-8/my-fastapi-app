from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from app.dependencies import AdminAccount, SessionDep, StaffAccount
from app.models import Branch, Inventory, Product, ProductCategory, utc_now
from app.schemas import (
    CategoryCreate,
    CategoryRead,
    CategoryUpdate,
    InventoryRead,
    InventorySet,
    InventoryTransferCreate,
    ProductCreate,
    ProductKind,
    ProductRead,
    ProductUpdate,
)

router = APIRouter(prefix="/api/v1", tags=["Catalog and inventory"])


@router.get("/categories", response_model=list[CategoryRead])
async def list_categories(session: SessionDep) -> list[ProductCategory]:
    return list(
        (
            await session.scalars(
                select(ProductCategory)
                .where(ProductCategory.is_active.is_(True))
                .order_by(ProductCategory.name)
            )
        ).all()
    )


@router.post("/admin/categories", response_model=CategoryRead, status_code=status.HTTP_201_CREATED)
async def create_category(
    payload: CategoryCreate, _: AdminAccount, session: SessionDep
) -> ProductCategory:
    category = ProductCategory(**payload.model_dump())
    session.add(category)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Category name already exists") from None
    await session.refresh(category)
    return category


@router.patch("/admin/categories/{category_id}", response_model=CategoryRead)
async def update_category(
    category_id: UUID, payload: CategoryUpdate, _: AdminAccount, session: SessionDep
) -> ProductCategory:
    category = await session.get(ProductCategory, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(category, key, value)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Category name already exists") from None
    await session.refresh(category)
    return category


@router.delete("/admin/categories/{category_id}", status_code=204)
async def deactivate_category(category_id: UUID, _: AdminAccount, session: SessionDep) -> None:
    category = await session.get(ProductCategory, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found")
    category.is_active = False
    await session.commit()


@router.get("/products", response_model=list[ProductRead])
async def list_products(
    session: SessionDep,
    kind: ProductKind | None = None,
    category_id: UUID | None = None,
    search: str | None = Query(default=None, min_length=1, max_length=100),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> list[Product]:
    statement = select(Product).where(Product.is_active.is_(True))
    if kind is not None:
        statement = statement.where(Product.kind == kind.value)
    if category_id is not None:
        statement = statement.where(Product.category_id == category_id)
    if search:
        statement = statement.where(Product.name.ilike(f"%{search}%"))
    statement = statement.order_by(Product.name).offset(offset).limit(limit)
    return list((await session.scalars(statement)).all())


@router.post("/admin/products", response_model=ProductRead, status_code=status.HTTP_201_CREATED)
async def create_product(payload: ProductCreate, _: AdminAccount, session: SessionDep) -> Product:
    if payload.category_id and await session.get(ProductCategory, payload.category_id) is None:
        raise HTTPException(status_code=404, detail="Category not found")
    product = Product(**payload.model_dump())
    product.kind = payload.kind.value
    session.add(product)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Product SKU already exists") from None
    await session.refresh(product)
    return product


@router.get("/admin/products", response_model=list[ProductRead])
async def list_all_products(
    _: StaffAccount,
    session: SessionDep,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
) -> list[Product]:
    return list(
        (
            await session.scalars(
                select(Product).order_by(Product.name).offset(offset).limit(limit)
            )
        ).all()
    )


@router.patch("/admin/products/{product_id}", response_model=ProductRead)
async def update_product(
    product_id: UUID, payload: ProductUpdate, _: AdminAccount, session: SessionDep
) -> Product:
    product = await session.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    changes = payload.model_dump(exclude_unset=True)
    if (
        changes.get("category_id")
        and await session.get(ProductCategory, changes["category_id"]) is None
    ):
        raise HTTPException(status_code=404, detail="Category not found")
    for key, value in changes.items():
        setattr(product, key, value)
    await session.commit()
    await session.refresh(product)
    return product


@router.delete("/admin/products/{product_id}", status_code=204)
async def deactivate_product(product_id: UUID, _: AdminAccount, session: SessionDep) -> None:
    product = await session.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    product.is_active = False
    await session.commit()


@router.get("/admin/inventory", response_model=list[InventoryRead])
async def list_inventory(
    _: StaffAccount,
    session: SessionDep,
    branch_id: UUID | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[Inventory]:
    statement = select(Inventory).order_by(Inventory.created_at.desc())
    if branch_id:
        statement = statement.where(Inventory.branch_id == branch_id)
    return list((await session.scalars(statement.offset(offset).limit(limit))).all())


@router.put("/admin/inventory/{branch_id}/{product_id}", response_model=InventoryRead)
async def set_inventory(
    branch_id: UUID,
    product_id: UUID,
    payload: InventorySet,
    _: AdminAccount,
    session: SessionDep,
) -> Inventory:
    branch = await session.get(Branch, branch_id)
    product = await session.get(Product, product_id)
    if branch is None or product is None:
        raise HTTPException(status_code=404, detail="Branch or product not found")
    inventory = await session.scalar(
        select(Inventory).where(
            Inventory.branch_id == branch_id, Inventory.product_id == product_id
        )
    )
    if inventory is None:
        inventory = Inventory(branch_id=branch_id, product_id=product_id, **payload.model_dump())
        session.add(inventory)
    else:
        inventory.quantity = payload.quantity
        inventory.reorder_level = payload.reorder_level
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Inventory row already exists") from None
    await session.refresh(inventory)
    return inventory


@router.post("/admin/inventory/transfers", status_code=201)
async def transfer_stock(
    payload: InventoryTransferCreate, _: AdminAccount, session: SessionDep
) -> dict[str, str | int]:
    # Lock branch rows in a stable order so simultaneous opposite-direction transfers serialize.
    branch_ids = sorted([payload.source_branch_id, payload.destination_branch_id], key=str)
    branches = list(
        (
            await session.scalars(
                select(Branch)
                .where(Branch.id.in_(branch_ids), Branch.is_active.is_(True))
                .order_by(Branch.id)
                .with_for_update()
            )
        ).all()
    )
    product = await session.get(Product, payload.product_id)
    if len(branches) != 2 or product is None or not product.is_active:
        await session.rollback()
        raise HTTPException(status_code=404, detail="Active branches and product are required")

    moved = await session.execute(
        update(Inventory)
        .where(
            Inventory.branch_id == payload.source_branch_id,
            Inventory.product_id == payload.product_id,
            Inventory.quantity >= payload.quantity,
        )
        .values(quantity=Inventory.quantity - payload.quantity, updated_at=utc_now())
    )
    if moved.rowcount != 1:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Source branch does not have enough stock")

    insert = pg_insert(Inventory).values(
        branch_id=payload.destination_branch_id,
        product_id=payload.product_id,
        quantity=payload.quantity,
        reorder_level=0,
    )
    await session.execute(
        insert.on_conflict_do_update(
            index_elements=[Inventory.branch_id, Inventory.product_id],
            set_={
                "quantity": Inventory.quantity + payload.quantity,
                "updated_at": utc_now(),
            },
        )
    )
    await session.commit()
    destination = await session.scalar(
        select(Inventory).where(
            Inventory.branch_id == payload.destination_branch_id,
            Inventory.product_id == payload.product_id,
        )
    )
    return {
        "status": "transferred",
        "product_id": str(payload.product_id),
        "quantity_moved": payload.quantity,
        "destination_quantity": destination.quantity if destination else payload.quantity,
    }
