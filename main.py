from fastapi import FastAPI, Depends
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

# Create the asynchronous database engine
engine = create_async_engine(DATABASE_URL, echo=True)

# Configure the session factory to generate async database sessions
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

app = FastAPI(title="Amr's FastAPI App", version="1.0")

# Dependency injection to handle opening and closing DB connections automatically per request
async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

@app.get("/")
async def root():
    return {"message": "Welcome to FastAPI on Ubuntu with Docker!"}

@app.get("/test-db")
async def test_db(db: AsyncSession = Depends(get_db)):
    try:
        # Execute a simple query to verify connection health with PostgreSQL
        result = await db.execute(text("SELECT version();"))
        db_version = result.scalar()
        return {
            "status": "success",
            "message": "Connected to PostgreSQL successfully!",
            "database_version": db_version
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}