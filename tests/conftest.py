import os

import pytest
from testcontainers.community.postgres import PostgresContainer


@pytest.fixture(scope="session")
def database_url():
    with PostgresContainer("postgres:16", driver="psycopg") as pg:
        # app.db builds its engine at import time, so the URL must be set before any app import
        os.environ["DATABASE_URL"] = pg.get_connection_url()
        from alembic import command
        from alembic.config import Config

        command.upgrade(Config("alembic.ini"), "head")
        yield os.environ["DATABASE_URL"]


@pytest.fixture(scope="session")
def client(database_url):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def db(database_url):
    from app.db import SessionLocal

    with SessionLocal() as session:
        yield session


@pytest.fixture
def order(client):
    return client.post("/orders", json={"amount_minor": 2500, "currency": "usd"}).json()
