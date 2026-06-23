import logging
import subprocess
import threading
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class Recorder:
    def __init__(self, streams: dict, recording_config: dict):
        self.streams = streams
        self.base_path = Path(recording_config["path"])
        self._defaults = recording_config          # global defaults; cameras may override
        self._lock = threading.Lock()
        self._processes: dict[str, subprocess.Popen] = {}
        self._current_files: dict[str, str] = {}

    def _resolve(self, camera_name: str, key: str, fallback):
        """Camera-level override → global default → hardcoded fallback."""
        cam_cfg = self.streams[camera_name].get("recording", {})
        return cam_cfg.get(key, self._defaults.get(key, fallback))

    def start(self, camera_name: str) -> dict:
        with self._lock:
            proc = self._processes.get(camera_name)
            if proc and proc.poll() is None:
                logger.info(f"{camera_name}: already recording")
                return self._status(camera_name)

            url = self.streams[camera_name]["path"]
            cam_dir = self.base_path / camera_name
            cam_dir.mkdir(parents=True, exist_ok=True)

            ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            out = cam_dir / f"{ts}.mkv"

            cmd = self._build_cmd(camera_name, url, str(out))
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self._processes[camera_name] = proc
            self._current_files[camera_name] = str(out)
            mode = "re-encode" if self._resolve(camera_name, "reencode", False) else "copy"
            logger.info(f"{camera_name}: started [{mode}] → {out} (pid={proc.pid})")
            return self._status(camera_name)

    def stop(self, camera_name: str) -> dict:
        with self._lock:
            proc = self._processes.get(camera_name)
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    logger.warning(f"{camera_name}: ffmpeg didn't stop gracefully, killing")
                    proc.kill()
                    proc.wait()
                logger.info(f"{camera_name}: stopped")
            self._processes.pop(camera_name, None)
            self._current_files.pop(camera_name, None)
            return self._status(camera_name)

    def status(self, camera_name: str) -> dict:
        with self._lock:
            return self._status(camera_name)

    def stop_all(self):
        for cam in list(self._processes.keys()):
            self.stop(cam)

    # ─── private ──────────────────────────────────────────────────────────────

    def _build_cmd(self, camera_name: str, url: str, out: str) -> list[str]:
        reencode     = self._resolve(camera_name, "reencode",       False)
        video_crf    = str(self._resolve(camera_name, "video_crf",  23))
        audio_bitrate = self._resolve(camera_name, "audio_bitrate", "128k")
        extra_args   = self._resolve(camera_name, "extra_args", "").split()
        logger.debug(f"{camera_name}: extra args: {extra_args}")

        base = [
            "ffmpeg",
            "-loglevel", "warning",
            "-rtsp_transport", "tcp",
            "-fflags", "+discardcorrupt+genpts",
            "-i", url,
        ]

        if reencode:
            codec = [
                "-c:v", "libx264", "-preset", "veryfast", "-crf", video_crf,
                "-c:a", "aac", "-b:a", audio_bitrate, "-ar", "44100",
                "-af", "aresample=async=1:min_hard_comp=0.100000:first_pts=0"
            ]
        else:
            codec = ["-c", "copy"]

        return base + codec + extra_args + ["-f", "matroska", out]

    def _status(self, camera_name: str) -> dict:
        """Must be called with self._lock held."""
        proc = self._processes.get(camera_name)
        recording = proc is not None and proc.poll() is None
        return {
            "camera": camera_name,
            "state": "recording" if recording else "stopped",
            "current_file": self._current_files.get(camera_name) if recording else None,
        }
