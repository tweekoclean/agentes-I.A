"""Ollama em localhost, com instalação verificada e pesos fora do Git."""
import asyncio
import hashlib
import logging
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import subprocess
import tarfile
import threading

import httpx

from .local_ai import local_ai_status


VERSION = "0.40.1"
ARCHIVE_SHA256 = "a7aebbe3dd76ccf1351a56a3e57218ad4863cb5f9a9938c58de87a37555e355d"
INSTALL_MARKER = ARCHIVE_SHA256 + ":cpu-2"
ARCHIVE_URL = f"https://github.com/ollama/ollama/releases/download/v{VERSION}/ollama-linux-amd64.tar.zst"
logger = logging.getLogger("atendeai.ia_local")


def memory_limit_mb():
    limits = []
    for name in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        try:
            value = int(Path(name).read_text().strip())
            if value < 1 << 60:
                limits.append(value // (1024 * 1024))
        except (OSError, ValueError):
            pass
    return min(limits) if limits else None


def cpu_limit_cores():
    try:
        quota, period = Path("/sys/fs/cgroup/cpu.max").read_text().split()
        if quota != "max" and int(quota) > 0 and int(period) > 0:
            return round(int(quota) / int(period), 2)
    except (OSError, ValueError):
        pass
    try:
        quota = int(Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us").read_text())
        period = int(Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us").read_text())
        if quota > 0 and period > 0:
            return round(quota / period, 2)
    except (OSError, ValueError):
        pass
    return None


def extract_cpu_runtime(archive, target):
    import zstandard
    with archive.open("rb") as source, zstandard.ZstdDecompressor().stream_reader(source) as reader:
        with tarfile.open(fileobj=reader, mode="r|") as package:
            for member in package:
                name = PurePosixPath(member.name.removeprefix("./"))
                if name.is_absolute() or ".." in name.parts:
                    raise ValueError("Caminho inválido no pacote Ollama.")
                if not (str(name) == "bin/ollama" or str(name).startswith("lib/ollama/")):
                    continue
                if any(part.startswith(("cuda", "rocm", "vulkan", "mlx")) for part in name.parts):
                    continue
                destination = target.joinpath(*name.parts)
                if not destination.resolve().is_relative_to(target.resolve()):
                    raise ValueError("Destino inválido no pacote Ollama.")
                destination.parent.mkdir(parents=True, exist_ok=True)
                if member.issym():
                    link = PurePosixPath(member.linkname)
                    resolved = destination.parent.joinpath(*link.parts).resolve()
                    if link.is_absolute() or not resolved.is_relative_to(target.resolve()):
                        raise ValueError("Link inválido no pacote Ollama.")
                    destination.symlink_to(str(link))
                    continue
                if not member.isfile():
                    continue
                with package.extractfile(member) as content, destination.open("wb") as output:
                    shutil.copyfileobj(content, output)
                destination.chmod(0o755 if member.mode & 0o111 else 0o644)
    if not (target / "bin/ollama").is_file():
        raise ValueError("O pacote não contém o executável Ollama.")


class LocalAIRuntime:
    def __init__(self, settings):
        self.settings = settings
        self.directory = Path(settings.local_ai_directory).resolve()
        self.stop = threading.Event()
        self.process = None
        self.state = "desabilitada" if not settings.local_ai_autostart else "aguardando_inicio"

    def install(self):
        if platform.system() != "Linux" or platform.machine() not in {"x86_64", "AMD64"}:
            raise ValueError("Instalação automática exige Linux x86_64. Use Ollama externo nesta plataforma.")
        target = self.directory / f"runtime-{VERSION}"
        marker = target / ".verified"
        if marker.is_file() and marker.read_text() == INSTALL_MARKER:
            return target / "bin/ollama"
        self.directory.mkdir(parents=True, exist_ok=True)
        archive = self.directory / "runtime.tar.zst.part"
        digest = hashlib.sha256()
        self.state = "baixando_runtime"
        logger.warning("IA local: baixando runtime Ollama %s; a API continua disponível.", VERSION)
        try:
            with httpx.Client(timeout=httpx.Timeout(60, connect=15), follow_redirects=True) as client:
                with client.stream("GET", ARCHIVE_URL) as response:
                    response.raise_for_status()
                    with archive.open("wb") as output:
                        for chunk in response.iter_bytes(1024 * 1024):
                            if self.stop.is_set():
                                raise InterruptedError()
                            digest.update(chunk)
                            output.write(chunk)
            if digest.hexdigest() != ARCHIVE_SHA256:
                raise ValueError("Checksum do runtime Ollama não confere.")
            self.state = "instalando_runtime"
            staging = self.directory / f"runtime-{VERSION}.part"
            if staging.exists():
                shutil.rmtree(staging)
            extract_cpu_runtime(archive, staging)
            (staging / ".verified").write_text(INSTALL_MARKER)
            if target.exists():
                shutil.rmtree(target)
            staging.rename(target)
        finally:
            archive.unlink(missing_ok=True)
        return target / "bin/ollama"

    def start_and_pull(self, binary):
        # Não entrega segredos do PostgreSQL, Meta ou painel ao processo do modelo.
        env = {name: os.environ[name] for name in ("PATH", "HOME", "TMPDIR", "LANG", "HTTP_PROXY", "HTTPS_PROXY",
                    "ALL_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy", "SSL_CERT_FILE", "SSL_CERT_DIR")
               if name in os.environ}
        env.update({"OLLAMA_HOST": "127.0.0.1:11434", "OLLAMA_NO_CLOUD": "1",
                    "OLLAMA_MODELS": str(self.directory / "models"), "OLLAMA_NUM_PARALLEL": "1",
                    "OLLAMA_MAX_LOADED_MODELS": "1", "OLLAMA_MAX_QUEUE": "8",
                    "OLLAMA_CONTEXT_LENGTH": str(self.settings.local_ai_context),
                    "CUDA_VISIBLE_DEVICES": "-1", "ROCR_VISIBLE_DEVICES": "-1"})
        self.state = "iniciando_runtime"
        self.process = subprocess.Popen([str(binary), "serve"], env=env,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        with httpx.Client(timeout=httpx.Timeout(60, connect=5), follow_redirects=False, trust_env=False) as client:
            for _ in range(60):
                if self.stop.is_set() or self.process.poll() is not None:
                    raise InterruptedError()
                try:
                    response = client.get("http://127.0.0.1:11434/api/version")
                    response.raise_for_status()
                    break
                except httpx.HTTPError:
                    self.stop.wait(1)
            else:
                raise TimeoutError("Runtime local não iniciou.")
            if not local_ai_status(self.settings)["pronta"]:
                self.state = "baixando_modelo"
                logger.warning("IA local: baixando modelo %s; aguarde antes de ativar nas empresas.", self.settings.local_ai_model)
                with client.stream("POST", "http://127.0.0.1:11434/api/pull",
                                   json={"model": self.settings.local_ai_model, "stream": True}) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        if self.stop.is_set():
                            raise InterruptedError()
                        if line:
                            import json
                            status = json.loads(line)
                            if "error" in status:
                                raise ValueError("Download do modelo não concluído.")
            if not local_ai_status(self.settings)["pronta"]:
                raise ValueError("Modelo ainda indisponível após o download.")
            self.state = "carregando_modelo"
            logger.warning("IA local: carregando o modelo em memória antes do primeiro atendimento.")
            response = client.post("http://127.0.0.1:11434/api/chat", timeout=self.settings.local_ai_timeout,
                                   json={"model": self.settings.local_ai_model, "messages": [], "stream": False,
                                         "keep_alive": f"{self.settings.local_ai_keep_alive_minutes}m",
                                         "options": {"num_ctx": self.settings.local_ai_context,
                                                     "num_thread": self.settings.local_ai_threads}})
            response.raise_for_status()
            if response.json().get("done") is not True:
                raise ValueError("Modelo não terminou de carregar em memória.")
        self.state = "pronta"
        logger.warning("IA local pronta: %s. Inferência sem cobrança por tokens.", self.settings.local_ai_model)

    async def run(self):
        limit = memory_limit_mb()
        required = {"qwen3:0.6b": 1400, "qwen3:1.7b": 2300, "qwen3:4b": 4096}.get(self.settings.local_ai_model, 4096)
        if limit is not None and limit < required:
            self.state = "memoria_insuficiente"
            logger.warning("IA local não iniciada: %s MB disponíveis; configure pelo menos %s MB.", limit, required)
            return
        try:
            binary = await asyncio.to_thread(self.install)
            if not self.stop.is_set():
                await asyncio.to_thread(self.start_and_pull, binary)
            while not self.stop.is_set():
                if self.process and self.process.poll() is not None:
                    self.state = "runtime_encerrado"
                    logger.error("IA local encerrada; reinicie a aplicação ou confira memória e CPU.")
                    return
                await asyncio.sleep(1)
        except Exception as error:
            if not self.stop.is_set():
                self.state = "falha_inicializacao"
                logger.error("Falha ao iniciar IA local (%s). Confira recursos e acesso ao download.", type(error).__name__)
        finally:
            if self.process and self.process.poll() is None:
                self.process.terminate()
                try:
                    await asyncio.to_thread(self.process.wait, timeout=10)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    await asyncio.to_thread(self.process.wait)

    def request_stop(self):
        self.stop.set()
