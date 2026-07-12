import os
import time
from typing import AsyncGenerator, List, Optional
from datetime import datetime

from fastapi import FastAPI, Depends, HTTPException, status, Query, Path, Body, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field
from dotenv import load_dotenv

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import String, Integer, Boolean, ForeignKey, DateTime, select, text

# ==============================================================================
# 1. ENVIRONMENT CONFIGURATION & LIFESPAN
# ==============================================================================

# Load environment variables explicitly from your .env file
load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is missing from your .env file!")

# Initialize the modern asynchronous SQLAlchemy engine using asyncpg
engine = create_async_engine(DATABASE_URL, echo=True)

# Build the session factory that generates localized asynchronous sessions
AsyncSessionLocal = async_sessionmaker(
    bind=engine, 
    class_=AsyncSession, 
    expire_on_commit=False
)

# Shared Database dependency inside endpoints to yield asynchronous sessions cleanly
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency injection function to manage database connection lifecycles.
    Yields an active database session per request and closes it upon completion.
    """
    async with AsyncSessionLocal() as session:
        yield session


# Modern Context Manager for managing FastAPI lifecycle startup/shutdown events
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Handles application startup and shutdown tasks smoothly.
    Automatically provisions database tables if they do not exist.
    """
    # Startup: Ensure connection health and create all tables automatically
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("🚀 Database tables synchronized. FastAPI Enterprise Application started!")
    
    yield  # Execution happens here during application lifetime
    
    # Shutdown: Safely dispose of open connection pools
    await engine.dispose()
    print("🛑 Connection pool cleaned up. FastAPI Enterprise Application stopped!")


# Core Application instance initialization leveraging modern lifespan architecture
app = FastAPI(
    title="Amr's Enterprise FastAPI Masterclass",
    description="A fully async production-grade Task Management API showcasing advanced FastAPI design patterns.",
    version="2.0.0",
    lifespan=lifespan
)

# ==============================================================================
# 2. DATABASE MODELS (SQLAlchemy 2.0 ORM Style)
# ==============================================================================

class Base(DeclarativeBase):
    """Unified base class for modern declarative SQLAlchemy mappings with explicit typing."""
    pass


class UserModel(Base):
    """Maps to the system users collection containing authentication properties."""
    __tablename__ = "system_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    email: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # One-to-Many Relationship: A user can own multiple tasks in the database
    tasks: Mapped[List["TaskModel"]] = relationship(
        "TaskModel", 
        back_populates="owner", 
        cascade="all, delete-orphan"
    )


class TaskModel(Base):
    """Maps to the application business tasks containing tracking metadata."""
    __tablename__ = "business_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    is_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Foreign Key setup referencing system_users database records
    owner_id: Mapped[int] = mapped_column(Integer, ForeignKey("system_users.id"), nullable=False)
    
    # Inverse relationship linking back directly to the UserModel owner
    owner: Mapped["UserModel"] = relationship("UserModel", back_populates="tasks")

# ==============================================================================
# 3. DATA VALIDATION SCHEMAS (Pydantic v2 Models)
# ==============================================================================

class TaskBase(BaseModel):
    title: str = Field(..., min_length=3, max_length=100, examples=["Deploy Backend Server"])
    description: Optional[str] = Field(None, max_length=500, examples=["Configure production uvicorn service"])

class TaskCreate(TaskBase):
    owner_id: int = Field(..., description="The ID of the user who owns this task")

class TaskUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=3, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    is_completed: Optional[bool] = Field(None)

class TaskResponse(TaskBase):
    id: int
    is_completed: bool
    created_at: datetime
    owner_id: int

    class Config:
        from_attributes = True


class UserBase(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, examples=["amr_galal"])
    email: EmailStr = Field(..., examples=["amr@example.com"])

class UserCreate(UserBase):
    pass

class UserResponse(UserBase):
    id: int
    is_active: bool
    created_at: datetime
    tasks: List[TaskResponse] = []

    class Config:
        from_attributes = True

# ==============================================================================
# 4. CUSTOM ADVANCED MIDDLEWARE & ERROR HANDLING
# ==============================================================================

@app.middleware("http")
async def add_performance_and_security_headers(request: Request, call_next):
    """
    Advanced HTTP Middleware capturing compute latency metrics 
    and outputting operational response headers dynamically.
    """
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    
    # Attach tracking metrics to the response payload headers
    response.headers["X-Process-Time-Seconds"] = str(process_time)
    response.headers["X-Application-Developer"] = "Amr Galal"
    return response


# Global Exception Interceptor overriding application runtime ValueError issues gracefully
@app.exception_handler(ValueError)
async def custom_value_error_handler(request: Request, exc: ValueError):
    """Catches unintended internal value discrepancies cleanly across operational endpoints."""
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"error_type": "InvalidValueProvided", "message": str(exc)}
    )

# ==============================================================================
# 5. ENTERPRISE ROUTERS & CORE ENDPOINTS
# ==============================================================================

@app.get("/health", tags=["System Monitoring"])
async def check_database_health(db: AsyncSession = Depends(get_db)):
    """Validates runtime connectivity status safely against PostgreSQL database layers."""
    try:
        start_time = time.time()
        result = await db.execute(text("SELECT 1;"))
        result.scalar()
        latency = (time.time() - start_time) * 1000
        return {
            "status": "healthy",
            "database": "PostgreSQL Operational",
            "latency_ms": round(latency, 2)
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database connectivity failed: {str(e)}"
        )


@app.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED, tags=["User Profiles"])
async def create_user(user: UserCreate, db: AsyncSession = Depends(get_db)):
    """Creates a new unique system user profile after validating email and username availability."""
    # Check if username or email already exists in async fashion
    stmt = select(UserModel).where((UserModel.username == user.username) | (UserModel.email == user.email))
    existing_user = await db.execute(stmt)
    if existing_user.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username or email has already been registered."
        )

    db_user = UserModel(username=user.username, email=user.email)
    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)
    return db_user


@app.get("/users", response_model=List[UserResponse], tags=["User Profiles"])
async def read_users(
    skip: int = Query(0, ge=0, description="Pagination skip offset amount"),
    limit: int = Query(10, ge=1, le=100, description="Pagination maximum data limit response size"),
    db: AsyncSession = Depends(get_db)
):
    """Retrieves all registered system user profiles bundled along with their respective tasks."""
    stmt = select(UserModel).offset(skip).limit(limit)
    result = await db.execute(stmt)
    users = result.scalars().all()
    return users


@app.post("/tasks", response_model=TaskResponse, status_code=status.HTTP_201_CREATED, tags=["Business Tasks"])
async def create_task(task: TaskCreate, db: AsyncSession = Depends(get_db)):
    """Allocates a fresh operational workflow task assigned strictly to an active user ID."""
    # Verify owner user entry exists first
    owner_check = await db.execute(select(UserModel).where(UserModel.id == task.owner_id))
    if not owner_check.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail=f"Target User owner with ID {task.owner_id} not found."
        )

    db_task = TaskModel(**task.model_dump())
    db.add(db_task)
    await db.commit()
    await db.refresh(db_task)
    return db_task


@app.get("/tasks/{task_id}", response_model=TaskResponse, tags=["Business Tasks"])
async def read_task(
    task_id: int = Path(..., description="The unique numerical ID of the business task", ge=1),
    db: AsyncSession = Depends(get_db)
):
    """Fetches full contextual details of a specific business task using its strict path identifier."""
    stmt = select(TaskModel).where(TaskModel.id == task_id)
    result = await db.execute(stmt)
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requested business task does not exist.")
    return task


@app.patch("/tasks/{task_id}", response_model=TaskResponse, tags=["Business Tasks"])
async def update_task(
    task_id: int = Path(..., ge=1),
    task_update: TaskUpdate = Body(..., description="Partial properties to safely mutate inside target task record"),
    db: AsyncSession = Depends(get_db)
):
    """Mutates specific granular task data properties iteratively without altering baseline metrics."""
    stmt = select(TaskModel).where(TaskModel.id == task_id)
    result = await db.execute(stmt)
    db_task = result.scalar_one_or_none()
    
    if not db_task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target task could not be tracked.")

    # Apply properties changes dynamically
    update_data = task_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_task, key, value)

    await db.commit()
    await db.refresh(db_task)
    return db_task


@app.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Business Tasks"])
async def delete_task(task_id: int = Path(..., ge=1), db: AsyncSession = Depends(get_db)):
    """Purges a business task completely from system records cleanly with proper memory cleanup."""
    stmt = select(TaskModel).where(TaskModel.id == task_id)
    result = await db.execute(stmt)
    task = result.scalar_one_or_none()
    
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target task cannot be fetched for deletion.")
        
    await db.delete(task)
    await db.commit()
    return None