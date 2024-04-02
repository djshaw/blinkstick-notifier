import time
from contextlib import contextmanager
from typing import Any, Generator

import docker
import docker.models
import docker.models.containers

from bitbucket_listener import MongoDataAccess
from process_context import find_free_port

class ManagedContainer:
    def __init__(self, container) -> None:
        self.container = container

@contextmanager
def managed_container( *args, **kwargs ) -> Generator[ManagedContainer, Any, None]:
    client = docker.from_env()
    client.ping()
    container = None
    try:
        container = client.containers.run(*args, detach=True, **kwargs)
        assert isinstance(container, docker.models.containers.Container)
        while container.status != "running":
            time.sleep(1)
            container = client.containers.get(container.id)
            assert isinstance(container, docker.models.containers.Container)
        yield ManagedContainer(container)
    finally:
        if container is not None and isinstance(container, docker.models.containers.Container):
            container.kill()
            container.remove()

class ManagedMongo(ManagedContainer):
    def __init__(self, container, mongo_port):
        super().__init__(container)
        self.mongo_port = mongo_port

@contextmanager
def managed_mongo() -> Generator[ManagedMongo, Any, None]:
    mongo_port = find_free_port()
    with managed_container("mongo",
                           ports={"27017": str(mongo_port)}
                            ) as container:
        data_access = None
        while data_access is None or not data_access.has_database():
            data_access = MongoDataAccess(f"mongodb://127.0.0.1:{mongo_port}/bitbucket")
        yield ManagedMongo(container.container, mongo_port)
