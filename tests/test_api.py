import pytest
from httpx import AsyncClient
import main

pytestmark = pytest.mark.asyncio


async def test_register_user(async_client: AsyncClient):
    response = await async_client.post("/register", json={"username": "newuser", "password": "pwd"})
    assert response.status_code == 200
    assert "access_token" in response.json()


async def test_register_duplicate_user(async_client: AsyncClient):
    await async_client.post("/register", json={"username": "dupuser", "password": "pwd"})
    response = await async_client.post("/register", json={"username": "dupuser", "password": "pwd"})
    assert response.status_code == 400
    assert "птички" in response.json()["detail"]


async def test_login_user(async_client: AsyncClient):
    await async_client.post("/register", json={"username": "loguser", "password": "pwd"})
    response = await async_client.post("/token", data={"username": "loguser", "password": "pwd"})
    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"


async def test_create_task(auth_client: AsyncClient):
    response = await auth_client.post("/tasks/", json={"title": "Buy milk", "priority": 5})
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Buy milk"
    assert data["priority"] == 5
    assert data["status"] == "ждём, ждём, ждём"


async def test_read_tasks_and_search(auth_client: AsyncClient):
    await auth_client.post("/tasks/", json={"title": "Buy milk", "description": "Lactose free"})
    await auth_client.post("/tasks/", json={"title": "Buy bread", "description": "Whole wheat"})

    # Запрос без фильтров
    response = await auth_client.get("/tasks/")
    assert len(response.json()) == 2

    # Запрос с поиском
    response_search = await auth_client.get("/tasks/?search=milk")
    assert len(response_search.json()) == 1
    assert response_search.json()[0]["title"] == "Buy milk"


async def test_update_task(auth_client: AsyncClient):
    create_resp = await auth_client.post("/tasks/", json={"title": "Old Task"})
    task_id = create_resp.json()["id"]

    update_resp = await auth_client.put(f"/tasks/{task_id}", json={
        "title": "New Task",
        "status": "работаем!",
        "priority": 10
    })
    assert update_resp.status_code == 200
    assert update_resp.json()["status"] == "работаем!"


async def test_delete_task(auth_client: AsyncClient):
    create_resp = await auth_client.post("/tasks/", json={"title": "To be deleted"})
    task_id = create_resp.json()["id"]

    delete_resp = await auth_client.delete(f"/tasks/{task_id}")
    assert delete_resp.status_code == 204

    # Проверяем, что таски больше нет
    get_resp = await auth_client.get(f"/tasks/{task_id}")
    assert get_resp.status_code == 404


async def test_top_tasks_cache(auth_client: AsyncClient):
    # Очищаем кэш перед тестом
    main.top_tasks_cache.clear()

    await auth_client.post("/tasks/", json={"title": "Low Priority", "priority": 1})
    await auth_client.post("/tasks/", json={"title": "High Priority", "priority": 100})

    # Первый вызов идет в БД и записывает в кэш
    response1 = await auth_client.get("/tasks/top/1")
    assert response1.status_code == 200
    assert response1.json()[0]["title"] == "High Priority"
    assert len(main.top_tasks_cache) > 0  # Проверяем, что кэш не пуст

    # Изменяем приоритет напрямую через другой эндпоинт, чтобы проверить кэш
    task_id = response1.json()[0]["id"]
    await auth_client.put(f"/tasks/{task_id}", json={"title": "High Priority", "priority": 0})

    # Второй вызов возвращает старые данные из кэша
    response2 = await auth_client.get("/tasks/top/1")
    assert response2.json()[0]["priority"] == 100