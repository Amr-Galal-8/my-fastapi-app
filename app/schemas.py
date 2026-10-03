from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints, model_validator

from app.models import FulfillmentMethod, OrderStatus, PaymentMethodType, ProductKind


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


Phone = Annotated[str, StringConstraints(strip_whitespace=True, min_length=7, max_length=32)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
Password = Annotated[str, StringConstraints(min_length=12, max_length=128)]


class TokenRead(StrictModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class ClientRegister(StrictModel):
    email: EmailStr
    password: Password
    first_name: ShortText
    last_name: ShortText
    phone: Phone


class ClientRead(ORMModel):
    id: UUID
    account_id: UUID
    email: EmailStr
    first_name: str
    last_name: str
    phone: str
    is_active: bool
    created_at: datetime


class ClientUpdate(StrictModel):
    email: EmailStr | None = None
    first_name: ShortText | None = None
    last_name: ShortText | None = None
    phone: Phone | None = None
    is_active: bool | None = None


class AddressCreate(StrictModel):
    label: str = Field(default="Home", min_length=1, max_length=40)
    recipient_name: ShortText
    phone: Phone
    line1: ShortText
    line2: str | None = Field(default=None, max_length=200)
    city: ShortText
    region: ShortText
    postal_code: str | None = Field(default=None, max_length=20)
    country: str = Field(default="EG", min_length=2, max_length=2)
    is_default: bool = False


class AddressRead(ORMModel):
    id: UUID
    label: str
    recipient_name: str
    phone: str
    line1: str
    line2: str | None
    city: str
    region: str
    postal_code: str | None
    country: str
    is_default: bool


class AddressUpdate(StrictModel):
    label: str | None = Field(default=None, min_length=1, max_length=40)
    recipient_name: ShortText | None = None
    phone: Phone | None = None
    line1: ShortText | None = None
    line2: str | None = Field(default=None, max_length=200)
    city: ShortText | None = None
    region: ShortText | None = None
    postal_code: str | None = Field(default=None, max_length=20)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    is_default: bool | None = None


class ClientProfileUpdate(StrictModel):
    email: EmailStr | None = None
    first_name: ShortText | None = None
    last_name: ShortText | None = None
    phone: Phone | None = None


class DepartmentCreate(StrictModel):
    code: str = Field(min_length=2, max_length=24, pattern=r"^[A-Za-z0-9_-]+$")
    name: ShortText
    description: str | None = Field(default=None, max_length=2000)


class DepartmentRead(ORMModel):
    id: UUID
    code: str
    name: str
    description: str | None
    is_active: bool


class DepartmentUpdate(StrictModel):
    code: str | None = Field(default=None, min_length=2, max_length=24, pattern=r"^[A-Za-z0-9_-]+$")
    name: ShortText | None = None
    description: str | None = Field(default=None, max_length=2000)
    is_active: bool | None = None


class BranchCreate(StrictModel):
    code: str = Field(min_length=2, max_length=24, pattern=r"^[A-Za-z0-9_-]+$")
    name: ShortText
    phone: Phone | None = None
    address_line: ShortText
    city: ShortText
    country: str = Field(default="EG", min_length=2, max_length=2)


class BranchRead(ORMModel):
    id: UUID
    code: str
    name: str
    phone: str | None
    address_line: str
    city: str
    country: str
    is_active: bool


class BranchUpdate(StrictModel):
    code: str | None = Field(default=None, min_length=2, max_length=24, pattern=r"^[A-Za-z0-9_-]+$")
    name: ShortText | None = None
    phone: Phone | None = None
    address_line: ShortText | None = None
    city: ShortText | None = None
    country: str | None = Field(default=None, min_length=2, max_length=2)
    is_active: bool | None = None


class EmployeeCreate(StrictModel):
    email: EmailStr
    password: Password
    employee_number: str = Field(min_length=2, max_length=32)
    first_name: ShortText
    last_name: ShortText
    title: ShortText
    department_id: UUID
    branch_id: UUID
    hired_on: date | None = None


class EmployeeRead(ORMModel):
    id: UUID
    account_id: UUID
    email: EmailStr
    employee_number: str
    first_name: str
    last_name: str
    title: str
    department_id: UUID
    branch_id: UUID
    hired_on: date
    is_active: bool


class EmployeeUpdate(StrictModel):
    email: EmailStr | None = None
    first_name: ShortText | None = None
    last_name: ShortText | None = None
    title: ShortText | None = None
    department_id: UUID | None = None
    branch_id: UUID | None = None
    is_active: bool | None = None


class CategoryCreate(StrictModel):
    name: ShortText
    description: str | None = Field(default=None, max_length=2000)


class CategoryRead(ORMModel):
    id: UUID
    name: str
    description: str | None
    is_active: bool


class CategoryUpdate(StrictModel):
    name: ShortText | None = None
    description: str | None = Field(default=None, max_length=2000)
    is_active: bool | None = None


class ProductCreate(StrictModel):
    sku: str = Field(min_length=2, max_length=48)
    name: ShortText
    description: str | None = Field(default=None, max_length=4000)
    kind: ProductKind
    category_id: UUID | None = None
    unit_price: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    currency: Literal["EGP"] = "EGP"


class ProductRead(ORMModel):
    id: UUID
    sku: str
    name: str
    description: str | None
    kind: ProductKind
    category_id: UUID | None
    unit_price: Decimal
    currency: str
    is_active: bool


class ProductUpdate(StrictModel):
    name: ShortText | None = None
    description: str | None = Field(default=None, max_length=4000)
    category_id: UUID | None = None
    unit_price: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    is_active: bool | None = None


class InventoryRead(ORMModel):
    id: UUID
    branch_id: UUID
    product_id: UUID
    quantity: int
    reorder_level: int
    updated_at: datetime


class InventorySet(StrictModel):
    quantity: int = Field(ge=0)
    reorder_level: int = Field(default=0, ge=0)


class InventoryTransferCreate(StrictModel):
    product_id: UUID
    source_branch_id: UUID
    destination_branch_id: UUID
    quantity: int = Field(gt=0, le=100000)

    @model_validator(mode="after")
    def branches_must_differ(self) -> "InventoryTransferCreate":
        if self.source_branch_id == self.destination_branch_id:
            raise ValueError("Source and destination branches must be different")
        return self


class OrderLineCreate(StrictModel):
    product_id: UUID
    quantity: int = Field(gt=0, le=100)


class ShippingAddress(StrictModel):
    recipient_name: ShortText
    phone: Phone
    line1: ShortText
    line2: str | None = Field(default=None, max_length=200)
    city: ShortText
    region: ShortText
    postal_code: str | None = Field(default=None, max_length=20)
    country: str = Field(default="EG", min_length=2, max_length=2)


class OrderCreate(StrictModel):
    items: list[OrderLineCreate] = Field(min_length=1, max_length=50)
    branch_id: UUID
    fulfillment_method: FulfillmentMethod
    payment_method: PaymentMethodType
    shipping_address: ShippingAddress | None = None
    shipping_address_id: UUID | None = None
    payment_method_id: UUID | None = None
    client_note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_fulfillment_and_payment(self) -> "OrderCreate":
        has_inline_address = self.shipping_address is not None
        has_saved_address = self.shipping_address_id is not None
        if self.fulfillment_method == FulfillmentMethod.HOME_DELIVERY and (
            has_inline_address == has_saved_address
        ):
            raise ValueError("Choose one shipping address for home delivery")
        if self.fulfillment_method == FulfillmentMethod.STORE_PICKUP and (
            has_inline_address or has_saved_address
        ):
            raise ValueError("Do not send a shipping address for store pickup")
        if self.payment_method == PaymentMethodType.CASH_ON_DELIVERY and self.payment_method_id:
            raise ValueError("A saved card cannot be used with cash on delivery")
        return self


class OrderItemRead(ORMModel):
    id: UUID
    product_id: UUID
    sku_snapshot: str
    product_name_snapshot: str
    quantity: int
    unit_price: Decimal
    line_total: Decimal


class PaymentRead(ORMModel):
    id: UUID
    provider: str
    status: str
    amount: Decimal
    currency: str
    checkout_url: str | None


class OrderRead(ORMModel):
    id: UUID
    order_number: str
    client_id: UUID
    branch_id: UUID
    fulfillment_method: FulfillmentMethod
    payment_method: PaymentMethodType
    status: OrderStatus
    payment_status: str
    total_amount: Decimal
    currency: str
    shipping_address: dict[str, Any] | None
    client_note: str | None
    items: list[OrderItemRead]
    payment: PaymentRead | None
    created_at: datetime


class OrderStatusUpdate(StrictModel):
    status: OrderStatus


class PaymentMethodRead(ORMModel):
    id: UUID
    provider: str
    brand: str
    last_four: str
    expiry_month: int | None
    expiry_year: int | None
    is_default: bool
    is_active: bool
    created_at: datetime


class MockCardSave(StrictModel):
    """Fake display metadata for a local demo; this schema never accepts a PAN or security code."""

    brand: str = Field(min_length=2, max_length=32)
    last_four: str = Field(pattern=r"^[0-9]{4}$")
    expiry_month: int = Field(ge=1, le=12)
    expiry_year: int = Field(ge=date.today().year, le=2100)
