from fastapi import FastAPI, Depends
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
import os
from dotenv import load_dotenv

# تحميل متغيرات البيئة من ملف .env
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

# إنشاء محرك الاتصال بالداتابيز بصيغة Async
engine = create_async_engine(DATABASE_URL, echo=True)

# تجهيز الـ Session المصنع اللي هيولد اتصالات مع الداتابيز
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

app = FastAPI(title="Amr's FastAPI App", version="1.0")

# دالة مساعدة (Dependency) لفتح وقفل الاتصال تلقائياً مع كل طلب
async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

@app.get("/")
async def root():
    return {"message": "Welcome to FastAPI on Ubuntu with Docker!"}

@app.get("/test-db")
async def test_db(db: AsyncSession = Depends(get_db)):
    try:
        # إرسال استعلام بسيط للتأكد من سلامة الاتصال بالـ PostgreSQL
        result = await db.execute(text("SELECT version();"))
        db_version = result.scalar()
        return {
            "status": "success",
            "message": "Connected to PostgreSQL successfully!",
            "database_version": db_version
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}