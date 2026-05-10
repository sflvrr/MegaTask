import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from main import app, Base, get_db

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"
engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestingSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

async def override_get_db():
    async with TestingSessionLocal() as session:
        yield session

app.dependency_overrides[get_db] = override_get_db

@pytest_asyncio.fixture(autouse=True)
async def prepare_database():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

@pytest_asyncio.fixture
async def async_client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client

@pytest_asyncio.fixture
async def auth_token(async_client: AsyncClient):
    # Регистрируем и логиним тестового пользователя
    user_data = {"username": "testuser", "password": "superpassword"}
    await async_client.post("/register", json=user_data)
    response = await async_client.post("/token", data=user_data)
    return response.json()["access_token"]

@pytest_asyncio.fixture
async def auth_client(async_client: AsyncClient, auth_token: str):
    # Клиент с предустановленным заголовком авторизации
    async_client.headers.update({"Authorization": f"Bearer {auth_token}"})
    yield async_client