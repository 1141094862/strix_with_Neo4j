import contextlib
import logging
import os
import secrets
import socket
import time
from pathlib import Path
from typing import Any, cast

import docker
from docker.errors import DockerException, ImageNotFound, NotFound
from docker.models.containers import Container

from .runtime import AbstractRuntime, SandboxInfo


STRIX_IMAGE = os.getenv("STRIX_IMAGE", "ghcr.io/usestrix/strix-sandbox:0.1.10")

# === Neo4j 配置 ===
NEO4J_IMAGE = os.getenv("NEO4J_IMAGE", "neo4j:5.12.0")
NEO4J_CONTAINER_NAME = "strix-neo4j-memory"

# 本地持久化路径
STRIX_DATA_ROOT = Path.home() / ".strix"
NEO4J_DATA_PATH = STRIX_DATA_ROOT / "neo4j" / "data"
NEO4J_LOGS_PATH = STRIX_DATA_ROOT / "neo4j" / "logs"

# 端口配置（固定端口，便于连接）
NEO4J_HTTP_PORT = int(os.getenv("NEO4J_HTTP_PORT", "7474"))
NEO4J_BOLT_PORT = int(os.getenv("NEO4J_BOLT_PORT", "7687"))

# 认证配置
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "strixpassword")

logger = logging.getLogger(__name__)


class DockerRuntime(AbstractRuntime):
    def __init__(self) -> None:
        try:
            self.client = docker.from_env()
        except DockerException as e:
            logger.exception("Failed to connect to Docker daemon")
            raise RuntimeError("Docker is not available or not configured correctly.") from e

        self._scan_container: Container | None = None
        self._tool_server_port: int | None = None
        self._tool_server_token: str | None = None

        # Neo4j 相关
        self._neo4j_container: Container | None = None
        self._neo4j_ready: bool = False

    def _ensure_neo4j_directories(self) -> None:
        """确保 Neo4j 本地持久化目录存在"""
        NEO4J_DATA_PATH.mkdir(parents=True, exist_ok=True)
        NEO4J_LOGS_PATH.mkdir(parents=True, exist_ok=True)
        logger.info(f"Neo4j data directory: {NEO4J_DATA_PATH}")

    def _check_neo4j_port_available(self) -> bool:
        """检查 Neo4j 端口是否可用"""
        for port in [NEO4J_BOLT_PORT, NEO4J_HTTP_PORT]:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                try:
                    s.bind(("127.0.0.1", port))
                except OSError:
                    logger.warning(f"Port {port} is already in use")
                    return False
        return True

    def _neo4j_container_exists(self) -> Container | None:
        """检查 Neo4j 容器是否存在"""
        try:
            container = self.client.containers.get(NEO4J_CONTAINER_NAME)
            return container
        except NotFound:
            return None
        except DockerException as e:
            logger.warning(f"Error checking Neo4j container: {e}")
            return None

    def _wait_for_neo4j_ready(self, container: Container, timeout: int = 60) -> bool:
        """等待 Neo4j 服务就绪"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                result = container.exec_run(
                    f"cypher-shell -u {NEO4J_USER} -p {NEO4J_PASSWORD} RETURN 1",
                    user="neo4j"
                )
                if result.exit_code == 0:
                    logger.info("Neo4j is ready")
                    self._neo4j_ready = True
                    return True
            except Exception:
                pass
            time.sleep(2)

        logger.warning("Neo4j failed to become ready within timeout")
        return False

    def _create_neo4j_container_with_retry(self, max_retries: int = 3) -> Container:
        """创建 Neo4j 容器（带重试机制）"""
        last_exception: Exception | None = None

        for attempt in range(max_retries):
            try:
                # 1. 验证镜像（复用现有方法）
                self._verify_image_available(NEO4J_IMAGE)

                # 2. 确保目录存在
                self._ensure_neo4j_directories()

                # 3. 检查端口
                if not self._check_neo4j_port_available():
                    raise RuntimeError("Neo4j ports are not available")

                # 4. 创建容器
                container = self.client.containers.run(
                    NEO4J_IMAGE,
                    name=NEO4J_CONTAINER_NAME,
                    detach=True,
                    ports={
                        f"{NEO4J_HTTP_PORT}/tcp": ("127.0.0.1", NEO4J_HTTP_PORT),
                        f"{NEO4J_BOLT_PORT}/tcp": ("127.0.0.1", NEO4J_BOLT_PORT),
                    },
                    volumes={
                        str(NEO4J_DATA_PATH): {"bind": "/data", "mode": "rw"},
                        str(NEO4J_LOGS_PATH): {"bind": "/logs", "mode": "rw"},
                    },
                    environment={
                        "NEO4J_AUTH": f"{NEO4J_USER}/{NEO4J_PASSWORD}",
                        "NEO4J_apoc_export_file_enabled": "true",
                        "NEO4J_apoc_import_file_enabled": "true",
                        "NEO4J_server_memory_pagecache_size": "512M",
                        "NEO4J_server_memory_heap_initial__size": "512M",
                        "NEO4J_server_memory_heap_max__size": "1G",
                    },
                    labels={"strix-service": "neo4j-memory"},
                )

                self._neo4j_container = container
                logger.info(f"Created Neo4j container: {container.id}")

                # 5. 等待就绪
                if self._wait_for_neo4j_ready(container):
                    return container
                else:
                    raise RuntimeError("Neo4j failed to start")

            except (DockerException, RuntimeError) as e:
                last_exception = e
                if attempt == max_retries - 1:
                    break

                logger.warning(f"Neo4j container creation attempt {attempt + 1}/{max_retries} failed")

                # 清理失败的容器
                with contextlib.suppress(Exception):
                    if self._neo4j_container:
                        self._neo4j_container.remove(force=True)
                        self._neo4j_container = None

                sleep_time = (2**attempt) + (0.1 * attempt)
                time.sleep(sleep_time)

        raise RuntimeError(
            f"Failed to create Neo4j container after {max_retries} attempts: {last_exception}"
        ) from last_exception

    def _get_or_create_neo4j_container(self) -> Container:
        """获取或创建 Neo4j 容器"""
        # 1. 检查内存中的引用
        if self._neo4j_container:
            try:
                self._neo4j_container.reload()
                if self._neo4j_container.status == "running":
                    if self._neo4j_ready:
                        return self._neo4j_container
            except NotFound:
                self._neo4j_container = None
                self._neo4j_ready = False

        # 2. 按名称查找容器
        existing = self._neo4j_container_exists()
        if existing:
            existing.reload()

            if existing.status != "running":
                logger.info("Starting existing Neo4j container")
                existing.start()

            self._neo4j_container = existing

            # 等待就绪
            if self._wait_for_neo4j_ready(existing):
                logger.info("Reusing existing Neo4j container")
                return existing
            else:
                logger.warning("Existing Neo4j container not ready, recreating")
                existing.remove(force=True)
                self._neo4j_container = None

        # 3. 创建新容器
        logger.info("Creating new Neo4j container")
        return self._create_neo4j_container_with_retry()

    def get_neo4j_info(self) -> dict[str, Any] | None:
        """获取 Neo4j 连接信息"""
        try:
            container = self._get_or_create_neo4j_container()

            if not container or not self._neo4j_ready:
                return None

            host = self._resolve_docker_host()

            return {
                "uri": f"bolt://{host}:{NEO4J_BOLT_PORT}",
                "user": NEO4J_USER,
                "password": NEO4J_PASSWORD,
                "http_port": NEO4J_HTTP_PORT,
                "bolt_port": NEO4J_BOLT_PORT,
                "container_id": container.id,
            }
        except RuntimeError:
            return None

    def stop_neo4j_container(self) -> None:
        """停止 Neo4j 容器（保留数据）"""
        if self._neo4j_container:
            self._neo4j_container.stop()
            self._neo4j_ready = False
            logger.info("Neo4j container stopped")

    def remove_neo4j_container(self) -> None:
        """删除 Neo4j 容器（数据保留在本地目录）"""
        if self._neo4j_container:
            self._neo4j_container.remove(force=True)
            self._neo4j_container = None
            self._neo4j_ready = False
            logger.info("Neo4j container removed")

    def _generate_sandbox_token(self) -> str:
        return secrets.token_urlsafe(32)

    def _find_available_port(self) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("", 0))
            return cast("int", s.getsockname()[1])

    def _get_scan_id(self, agent_id: str) -> str:
        try:
            from strix.telemetry.tracer import get_global_tracer

            tracer = get_global_tracer()
            if tracer and tracer.scan_config:
                return str(tracer.scan_config.get("scan_id", "default-scan"))
        except ImportError:
            logger.debug("Failed to import tracer, using fallback scan ID")
        except AttributeError:
            logger.debug("Tracer missing scan_config, using fallback scan ID")

        return f"scan-{agent_id.split('-')[0]}"

    def _verify_image_available(self, image_name: str, max_retries: int = 3) -> None:
        def _validate_image(image: docker.models.images.Image) -> None:
            if not image.id or not image.attrs:
                raise ImageNotFound(f"Image {image_name} metadata incomplete")

        for attempt in range(max_retries):
            try:
                image = self.client.images.get(image_name)
                _validate_image(image)
            except ImageNotFound:
                if attempt == max_retries - 1:
                    logger.exception(f"Image {image_name} not found after {max_retries} attempts")
                    raise
                logger.warning(f"Image {image_name} not ready, attempt {attempt + 1}/{max_retries}")
                time.sleep(2**attempt)
            except DockerException:
                if attempt == max_retries - 1:
                    logger.exception(f"Failed to verify image {image_name}")
                    raise
                logger.warning(f"Docker error verifying image, attempt {attempt + 1}/{max_retries}")
                time.sleep(2**attempt)
            else:
                logger.debug(f"Image {image_name} verified as available")
                return

    def _create_container_with_retry(self, scan_id: str, max_retries: int = 3) -> Container:
        last_exception = None
        container_name = f"strix-scan-{scan_id}"

        for attempt in range(max_retries):
            try:
                self._verify_image_available(STRIX_IMAGE)

                try:
                    existing_container = self.client.containers.get(container_name)
                    logger.warning(f"Container {container_name} already exists, removing it")
                    with contextlib.suppress(Exception):
                        existing_container.stop(timeout=5)
                    existing_container.remove(force=True)
                    time.sleep(1)
                except NotFound:
                    pass
                except DockerException as e:
                    logger.warning(f"Error checking/removing existing container: {e}")

                caido_port = self._find_available_port()
                tool_server_port = self._find_available_port()
                tool_server_token = self._generate_sandbox_token()

                self._tool_server_port = tool_server_port
                self._tool_server_token = tool_server_token

                container = self.client.containers.run(
                    STRIX_IMAGE,
                    command="sleep infinity",
                    detach=True,
                    name=container_name,
                    hostname=f"strix-scan-{scan_id}",
                    ports={
                        f"{caido_port}/tcp": caido_port,
                        f"{tool_server_port}/tcp": tool_server_port,
                    },
                    cap_add=["NET_ADMIN", "NET_RAW"],
                    labels={"strix-scan-id": scan_id},
                    environment={
                        "PYTHONUNBUFFERED": "1",
                        "CAIDO_PORT": str(caido_port),
                        "TOOL_SERVER_PORT": str(tool_server_port),
                        "TOOL_SERVER_TOKEN": tool_server_token,
                    },
                    tty=True,
                )

                self._scan_container = container
                logger.info("Created container %s for scan %s", container.id, scan_id)

                self._initialize_container(
                    container, caido_port, tool_server_port, tool_server_token
                )
            except DockerException as e:
                last_exception = e
                if attempt == max_retries - 1:
                    logger.exception(f"Failed to create container after {max_retries} attempts")
                    break

                logger.warning(f"Container creation attempt {attempt + 1}/{max_retries} failed")

                self._tool_server_port = None
                self._tool_server_token = None

                sleep_time = (2**attempt) + (0.1 * attempt)
                time.sleep(sleep_time)
            else:
                return container

        raise RuntimeError(
            f"Failed to create Docker container after {max_retries} attempts: {last_exception}"
        ) from last_exception

    def _get_or_create_scan_container(self, scan_id: str) -> Container:  # noqa: PLR0912
        container_name = f"strix-scan-{scan_id}"

        if self._scan_container:
            try:
                self._scan_container.reload()
                if self._scan_container.status == "running":
                    return self._scan_container
            except NotFound:
                self._scan_container = None
                self._tool_server_port = None
                self._tool_server_token = None

        try:
            container = self.client.containers.get(container_name)
            container.reload()

            if (
                "strix-scan-id" not in container.labels
                or container.labels["strix-scan-id"] != scan_id
            ):
                logger.warning(
                    f"Container {container_name} exists but missing/wrong label, updating"
                )

            if container.status != "running":
                logger.info(f"Starting existing container {container_name}")
                container.start()
                time.sleep(2)

            self._scan_container = container

            for env_var in container.attrs["Config"]["Env"]:
                if env_var.startswith("TOOL_SERVER_PORT="):
                    self._tool_server_port = int(env_var.split("=")[1])
                elif env_var.startswith("TOOL_SERVER_TOKEN="):
                    self._tool_server_token = env_var.split("=")[1]

            logger.info(f"Reusing existing container {container_name}")

        except NotFound:
            pass
        except DockerException as e:
            logger.warning(f"Failed to get container by name {container_name}: {e}")
        else:
            return container

        try:
            containers = self.client.containers.list(
                all=True, filters={"label": f"strix-scan-id={scan_id}"}
            )
            if containers:
                container = containers[0]
                if container.status != "running":
                    container.start()
                    time.sleep(2)
                self._scan_container = container

                for env_var in container.attrs["Config"]["Env"]:
                    if env_var.startswith("TOOL_SERVER_PORT="):
                        self._tool_server_port = int(env_var.split("=")[1])
                    elif env_var.startswith("TOOL_SERVER_TOKEN="):
                        self._tool_server_token = env_var.split("=")[1]

                logger.info(f"Found existing container by label for scan {scan_id}")
                return container
        except DockerException as e:
            logger.warning("Failed to find existing container by label for scan %s: %s", scan_id, e)

        logger.info("Creating new Docker container for scan %s", scan_id)
        return self._create_container_with_retry(scan_id)

    def _initialize_container(
        self, container: Container, caido_port: int, tool_server_port: int, tool_server_token: str
    ) -> None:
        logger.info("Initializing Caido proxy on port %s", caido_port)
        result = container.exec_run(
            f"bash -c 'export CAIDO_PORT={caido_port} && /usr/local/bin/docker-entrypoint.sh true'",
            detach=False,
        )

        time.sleep(5)

        result = container.exec_run(
            "bash -c 'source /etc/profile.d/proxy.sh && echo $CAIDO_API_TOKEN'", user="pentester"
        )
        caido_token = result.output.decode().strip() if result.exit_code == 0 else ""

        container.exec_run(
            f"bash -c 'source /etc/profile.d/proxy.sh && cd /app && "
            f"STRIX_SANDBOX_MODE=true CAIDO_API_TOKEN={caido_token} CAIDO_PORT={caido_port} "
            f"poetry run python strix/runtime/tool_server.py --token {tool_server_token} "
            f"--host 0.0.0.0 --port {tool_server_port} &'",
            detach=True,
            user="pentester",
        )

        time.sleep(5)

    def _copy_local_directory_to_container(
        self, container: Container, local_path: str, target_name: str | None = None
    ) -> None:
        import tarfile
        from io import BytesIO

        try:
            local_path_obj = Path(local_path).resolve()
            if not local_path_obj.exists() or not local_path_obj.is_dir():
                logger.warning(f"Local path does not exist or is not directory: {local_path_obj}")
                return

            if target_name:
                logger.info(
                    f"Copying local directory {local_path_obj} to container at "
                    f"/workspace/{target_name}"
                )
            else:
                logger.info(f"Copying local directory {local_path_obj} to container")

            tar_buffer = BytesIO()
            with tarfile.open(fileobj=tar_buffer, mode="w") as tar:
                for item in local_path_obj.rglob("*"):
                    if item.is_file():
                        rel_path = item.relative_to(local_path_obj)
                        arcname = Path(target_name) / rel_path if target_name else rel_path
                        tar.add(item, arcname=arcname)

            tar_buffer.seek(0)
            container.put_archive("/workspace", tar_buffer.getvalue())

            container.exec_run(
                "chown -R pentester:pentester /workspace && chmod -R 755 /workspace",
                user="root",
            )

            logger.info("Successfully copied local directory to /workspace")

        except (OSError, DockerException):
            logger.exception("Failed to copy local directory to container")

    async def create_sandbox(
        self,
        agent_id: str,
        existing_token: str | None = None,
        local_sources: list[dict[str, str]] | None = None,
    ) -> SandboxInfo:
        # === 确保 Neo4j 记忆核心就绪 ===
        try:
            self._get_or_create_neo4j_container()
        except RuntimeError as e:
            logger.warning(f"Neo4j initialization failed: {e}")
            logger.warning("Continuing without Neo4j memory backend")

        scan_id = self._get_scan_id(agent_id)
        container = self._get_or_create_scan_container(scan_id)

        source_copied_key = f"_source_copied_{scan_id}"
        if local_sources and not hasattr(self, source_copied_key):
            for index, source in enumerate(local_sources, start=1):
                source_path = source.get("source_path")
                if not source_path:
                    continue

                target_name = source.get("workspace_subdir")
                if not target_name:
                    target_name = Path(source_path).name or f"target_{index}"

                self._copy_local_directory_to_container(container, source_path, target_name)
            setattr(self, source_copied_key, True)

        container_id = container.id
        if container_id is None:
            raise RuntimeError("Docker container ID is unexpectedly None")

        token = existing_token if existing_token is not None else self._tool_server_token

        if self._tool_server_port is None or token is None:
            raise RuntimeError("Tool server not initialized or no token available")

        api_url = await self.get_sandbox_url(container_id, self._tool_server_port)

        await self._register_agent_with_tool_server(api_url, agent_id, token)

        return {
            "workspace_id": container_id,
            "api_url": api_url,
            "auth_token": token,
            "tool_server_port": self._tool_server_port,
            "agent_id": agent_id,
        }

    async def _register_agent_with_tool_server(
        self, api_url: str, agent_id: str, token: str
    ) -> None:
        import httpx

        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                response = await client.post(
                    f"{api_url}/register_agent",
                    params={"agent_id": agent_id},
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=30,
                )
                response.raise_for_status()
                logger.info(f"Registered agent {agent_id} with tool server")
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            logger.warning(f"Failed to register agent {agent_id}: {e}")

    async def get_sandbox_url(self, container_id: str, port: int) -> str:
        try:
            container = self.client.containers.get(container_id)
            container.reload()

            host = self._resolve_docker_host()

        except NotFound:
            raise ValueError(f"Container {container_id} not found.") from None
        except DockerException as e:
            raise RuntimeError(f"Failed to get container URL for {container_id}: {e}") from e
        else:
            return f"http://{host}:{port}"

    def _resolve_docker_host(self) -> str:
        docker_host = os.getenv("DOCKER_HOST", "")
        if not docker_host:
            return "127.0.0.1"

        from urllib.parse import urlparse

        parsed = urlparse(docker_host)

        if parsed.scheme in ("tcp", "http", "https") and parsed.hostname:
            return parsed.hostname

        return "127.0.0.1"

    async def destroy_sandbox(self, container_id: str) -> None:
        logger.info("Destroying scan container %s", container_id)
        try:
            container = self.client.containers.get(container_id)
            container.stop()
            container.remove()
            logger.info("Successfully destroyed container %s", container_id)

            self._scan_container = None
            self._tool_server_port = None
            self._tool_server_token = None

        except NotFound:
            logger.warning("Container %s not found for destruction.", container_id)
        except DockerException as e:
            logger.warning("Failed to destroy container %s: %s", container_id, e)
