import random
import string
from locust import HttpUser, task, between


def random_string(length=8):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))


class TaskManagerUser(HttpUser):
    wait_time = between(1, 3)  # Имитация задержки между действиями пользователя

    def on_start(self):
        self.username = random_string()
        self.password = "secure_password"
        self.headers = {}

        # Регистрация
        self.client.post("/register", json={"username": self.username, "password": self.password})

        # Логин
        response = self.client.post("/token", data={"username": self.username, "password": self.password})
        if response.status_code == 200:
            token = response.json()["access_token"]
            self.headers = {"Authorization": f"Bearer {token}"}

    @task(3)
    def create_task(self):
        if self.headers:
            self.client.post(
                "/tasks/",
                json={
                    "title": f"Load Test Task {random_string(5)}",
                    "description": "Created by Locust",
                    "priority": random.randint(1, 100)
                },
                headers=self.headers
            )

    @task(2)
    def list_tasks(self):
        if self.headers:
            self.client.get("/tasks/?sort_by=created_at&order=desc", headers=self.headers)

    @task(5)
    def get_top_tasks(self):
        # Этот эндпоинт кэшируется, поэтому его запрашиваем чаще
        if self.headers:
            self.client.get("/tasks/top/5", headers=self.headers, name="/tasks/top/[n]")