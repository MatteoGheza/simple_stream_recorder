import atexit
import logging
import yaml
from flask import Flask, jsonify, request, abort

from .recorder import Recorder
from .mqtt_client import MQTTClient

logger = logging.getLogger(__name__)

def load_config(path: str = "config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)

def create_app(config_path: str = "config.yaml") -> Flask:
    """Application factory to configure and return the Flask server."""
    
    # 1. Setup logging configuration inside the runner lifecycle
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    app = Flask(__name__)
    
    # 2. Load configurations and instantiate workers
    config = load_config(config_path)
    recorder = Recorder(
        streams=config["streams"],
        recording_config=config["recording"],
    )
    
    mqtt = None
    mqtt_cfg = config.get("mqtt", {})
    if mqtt_cfg.get("broker"):
        mqtt = MQTTClient(mqtt_cfg, config["streams"], recorder)
        mqtt.connect()
    else:
        logger.warning("No MQTT broker configured — running without MQTT")

    # 3. Teardown / Cleanup
    def _cleanup():
        logger.info("Shutdown: stopping all recordings")
        recorder.stop_all()
        if mqtt:
            mqtt.disconnect()

    atexit.register(_cleanup)

    # 4. Helpers and Inner Routing Logic
    def require_auth():
        expected = f"Bearer {config['api']['token']}"
        if request.headers.get("Authorization", "") != expected:
            abort(401)

    def camera_or_404(camera_name: str):
        if camera_name not in config["streams"]:
            abort(404, description=f"Unknown camera: {camera_name}")

    def _notify_mqtt(camera_name: str):
        if mqtt:
            state = recorder.status(camera_name)["state"]
            mqtt.publish_status(camera_name, state)

    # 5. Route Definitions
    @app.post("/<camera_name>/start")
    def start(camera_name: str):
        require_auth()
        camera_or_404(camera_name)
        result = recorder.start(camera_name)
        _notify_mqtt(camera_name)
        return jsonify(result)

    @app.post("/<camera_name>/stop")
    def stop(camera_name: str):
        require_auth()
        camera_or_404(camera_name)
        result = recorder.stop(camera_name)
        _notify_mqtt(camera_name)
        return jsonify(result)

    @app.get("/<camera_name>/status")
    def get_status(camera_name: str):
        require_auth()
        camera_or_404(camera_name)
        return jsonify(recorder.status(camera_name))

    # 6. Error Handlers
    @app.errorhandler(401)
    def unauthorized(e):
        return jsonify({"error": "Unauthorized"}), 401

    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"error": str(e)}), 404

    return app
