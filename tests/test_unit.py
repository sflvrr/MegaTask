from datetime import timedelta
import jwt
from main import verify_password, get_password_hash, create_access_token, SECRET_KEY, ALGORITHM


def test_password_hashing():
    password = "my_secure_password"
    hashed = get_password_hash(password)

    assert password != hashed
    assert verify_password(password, hashed) is True
    assert verify_password("wrong_password", hashed) is False


def test_create_access_token():
    data = {"sub": "test_user"}
    token = create_access_token(data, expires_delta=timedelta(minutes=10))

    # Проверяем, что токен валидный и содержит нужный payload
    decoded = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    assert decoded["sub"] == "test_user"
    assert "exp" in decoded                                                                                           