# Пояснения закинул в файлик README

import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import List, Optional

from fastapi import FastAPI, Depends, HTTPException, status, Query
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
import jwt
from jwt.exceptions import InvalidTokenError
from passlib.context import CryptContext
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Enum as SQLEnum, select, or_, desc, asc
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base, relationship

SECRET_KEY = "super-secret-key-for-fastapi-course" # Ну по-хорошему надо бы .env делать, но тут не буду, потому что пока не релиз
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

DATABASE_URL = "sqlite+aiosqlite:///./tasks.db"
engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

Base = declarative_base()


class TaskStatus(str, Enum):
    PENDING = "ждём, ждём, ждём"
    IN_PROGRESS = "работаем!"
    COMPLETED = "Опа! У меня тоже есть птички... Таска завершена, про птичек тут просто так."


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    tasks = relationship("Task", back_populates="owner")


class Task(Base):
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)
    description = Column(Text)
    status = Column(SQLEnum(TaskStatus), default=TaskStatus.PENDING)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    priority = Column(Integer, default=0)
    owner_id = Column(Integer, ForeignKey("users.id"))

    owner = relationship("User", back_populates="tasks")


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


app = FastAPI(lifespan=lifespan, title="MegaTask")


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


class UserCreate(BaseModel):
    username: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str


class TaskBase(BaseModel):
    title: str
    description: Optional[str] = None
    status: TaskStatus = TaskStatus.PENDING
    priority: int = 0


class TaskCreate(TaskBase):
    pass


class TaskUpdate(TaskBase):
    pass


class TaskRead(TaskBase):
    id: int
    created_at: datetime
    owner_id: int
    model_config = ConfigDict(from_attributes=True)


def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password):
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


async def get_current_user(token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except InvalidTokenError:
        raise credentials_exception

    stmt = select(User).where(User.username == username)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if user is None:
        raise credentials_exception
    return user


@app.post("/register", response_model=Token)
async def register(user: UserCreate, db: AsyncSession = Depends(get_db)):
    stmt = select(User).where(User.username == user.username)
    result = await db.execute(stmt)
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Опа! У меня тоже есть птички, и в отличие от твоих, они уже взяли этот юзернейм... Выбери другой!")

    hashed_password = get_password_hash(user.password)
    new_user = User(username=user.username, hashed_password=hashed_password)
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    access_token = create_access_token(data={"sub": new_user.username})
    return {"access_token": access_token, "token_type": "bearer"}


@app.post("/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)):
    stmt = select(User).where(User.username == form_data.username)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect username or password",
                            headers={"WWW-Authenticate": "Bearer"})

    access_token = create_access_token(data={"sub": user.username},
                                       expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    return {"access_token": access_token, "token_type": "bearer"}


top_tasks_cache = {}
CACHE_TTL = 30


@app.post("/tasks/", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
async def create_task(task: TaskCreate, db: AsyncSession = Depends(get_db),
                      current_user: User = Depends(get_current_user)):
    db_task = Task(**task.model_dump(), owner_id=current_user.id)
    db.add(db_task)
    await db.commit()
    await db.refresh(db_task)
    return db_task


@app.get("/tasks/", response_model=List[TaskRead])
async def read_tasks(
        search: Optional[str] = None,
        sort_by: Optional[str] = Query(None, description="Поля: title, status, created_at"),
        order: Optional[str] = Query("asc", description="asc или desc"),
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    stmt = select(Task).where(Task.owner_id == current_user.id)

    if search:
        stmt = stmt.where(or_(Task.title.contains(search), Task.description.contains(search)))

    if sort_by:
        order_func = desc if order == "desc" else asc
        if sort_by == "title":
            stmt = stmt.order_by(order_func(Task.title))
        elif sort_by == "status":
            stmt = stmt.order_by(order_func(Task.status))
        elif sort_by == "created_at":
            stmt = stmt.order_by(order_func(Task.created_at))

    result = await db.execute(stmt)
    return result.scalars().all()


@app.get("/tasks/top/{n}", response_model=List[TaskRead])
async def get_top_tasks(n: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    now = time.time()
    user_cache = top_tasks_cache.get(current_user.id)

    if user_cache and user_cache["expires"] > now:
        return user_cache["data"]

    stmt = select(Task).where(Task.owner_id == current_user.id).order_by(desc(Task.priority)).limit(n)
    result = await db.execute(stmt)
    tasks = result.scalars().all()

    top_tasks_cache[current_user.id] = {"data": tasks, "expires": now + CACHE_TTL}

    return tasks


@app.get("/tasks/{task_id}", response_model=TaskRead)
async def read_task(task_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    stmt = select(Task).where(Task.id == task_id, Task.owner_id == current_user.id)
    result = await db.execute(stmt)
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="Опа! У меня тоже есть птички, и у них, в отличие от твоих, есть таски... А вот твоя не найдена!")
    return task


@app.put("/tasks/{task_id}", response_model=TaskRead)
async def update_task(task_id: int, task_update: TaskUpdate, db: AsyncSession = Depends(get_db),
                      current_user: User = Depends(get_current_user)):
    stmt = select(Task).where(Task.id == task_id, Task.owner_id == current_user.id)
    result = await db.execute(stmt)
    db_task = result.scalar_one_or_none()

    if db_task is None:
        raise HTTPException(status_code=404, detail="Опа! У меня тоже есть птички, и у них, в отличие от твоих, есть таски... А вот твоя не найдена!")

    for key, value in task_update.model_dump().items():
        setattr(db_task, key, value)

    await db.commit()
    await db.refresh(db_task)
    return db_task


@app.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(task_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    stmt = select(Task).where(Task.id == task_id, Task.owner_id == current_user.id)
    result = await db.execute(stmt)
    db_task = result.scalar_one_or_none()

    if db_task is None:
        raise HTTPException(status_code=404, detail="Опа! У меня тоже есть птички, и у них, в отличие от твоих, есть таски... А вот твоя не найдена!")

    await db.delete(db_task)
    await db.commit()
    return None


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)