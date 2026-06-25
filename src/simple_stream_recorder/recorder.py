import logging
import re
import subprocess
import threading
import time
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
        
        # Tracks the last time a speed warning was logged to prevent log spam
        self._last_speed_warning: dict[str, float] = {}

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
            
            log_ffmpeg = self._resolve(camera_name, "log_ffmpeg", True)
            stderr_dest = subprocess.PIPE if log_ffmpeg else subprocess.DEVNULL

            proc = subprocess.Popen(
                cmd, 
                stdout=subprocess.DEVNULL, 
                stderr=stderr_dest,
                text=True,
                errors="replace"
            )
            
            self._processes[camera_name] = proc
            self._current_files[camera_name] = str(out)
            
            if log_ffmpeg:
                t = threading.Thread(
                    target=self._read_stderr, 
                    args=(camera_name, proc), 
                    daemon=True
                )
                t.start()

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
            self._last_speed_warning.pop(camera_name, None)
            return self._status(camera_name)

    def status(self, camera_name: str) -> dict:
        with self._lock:
            return self._status(camera_name)

    def stop_all(self):
        for cam in list(self._processes.keys()):
            self.stop(cam)

    # ─── private ──────────────────────────────────────────────────────────────

    def _read_stderr(self, camera_name: str, proc: subprocess.Popen):
        """Reads FFmpeg's stderr, filters out stats, and checks processing speed."""
        if not proc.stderr:
            return

        # Matches speed value formats like "speed= 0.85x" or "speed=1.02x"
        speed_regex = re.compile(r'speed=\s*([0-9.]+)\s*x')

        for line in iter(proc.stderr.readline, ''):
            # Check if this line is an FFmpeg periodic stats update
            speed_match = speed_regex.search(line)
            
            if speed_match:
                try:
                    speed_val = float(speed_match.group(1))
                    if speed_val < 1.0:
                        now = time.time()
                        # Only log a warning once every 5 seconds to prevent log bloat
                        if now - self._last_speed_warning.get(camera_name, 0) > 5:
                            logger.warning(
                                f"[{camera_name} FFmpeg] Performance bottleneck! "
                                f"Encoding speed dropped to {speed_val}x (falling behind real-time)"
                            )
                            self._last_speed_warning[camera_name] = now
                except ValueError:
                    pass  # Safely catch instances where speed might temporarily be "N/A"
            
            elif "frame=" not in line:
                # If it doesn't contain performance stats, it's a legitimate error or warning
                cleaned_line = line.strip()
                if cleaned_line:
                    logger.warning(f"[{camera_name} FFmpeg] {cleaned_line}")

        proc.stderr.close()

    def _build_cmd(self, camera_name: str, url: str, out: str) -> list[str]:
        reencode     = self._resolve(camera_name, "reencode",       False)
        video_crf    = str(self._resolve(camera_name, "video_crf",  23))
        audio_bitrate = self._resolve(camera_name, "audio_bitrate", "128k")
        extra_args   = self._resolve(camera_name, "extra_args", "").split()
        encoding_method = self._resolve(camera_name, "encoding_method", "libx264")
        quality_name_param = "-crf" if encoding_method == "libx264" else "-qp" if encoding_method == "h264_vaapi" else "-q:v"
        preset = self._resolve(camera_name, "preset", "veryfast")
        logger.debug(f"{camera_name}: extra args: {extra_args}, encoding: {encoding_method}, preset: {preset}")

        base = [
            "ffmpeg",
            "-loglevel", "warning",
            "-stats"  # Force stats output despite the 'warning' loglevel layout
        ]
        if url.startswith("rtsp://"):
            base += [
                "-rtsp_transport", "tcp"
            ]
        base += [
            "-thread_queue_size", "2048",
            "-buffer_size", "20000000",
            "-fflags", "+genpts",
            "-i", url,
        ]

        if reencode:
            codec = [
                "-c:v", encoding_method, "-preset", preset, quality_name_param, video_crf,
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
