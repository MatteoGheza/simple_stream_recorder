import json
import logging
import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)

BASE_TOPIC = "simple_stream_recorder"
HA_PREFIX = "homeassistant"


def _make_client(client_id: str) -> mqtt.Client:
    """Instantiate paho Client compatible with both paho-mqtt 1.x and 2.x."""
    try:
        return mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION1, # type: ignore
            client_id=client_id,
            clean_session=True,
        )
    except AttributeError:
        # paho-mqtt < 2.0
        return mqtt.Client(client_id=client_id, clean_session=True)


class MQTTClient:
    def __init__(self, config: dict, streams: dict, recorder):
        self.config = config
        self.streams = streams
        self.recorder = recorder

        self.client = _make_client("simple_stream_recorder")
        if config.get("username"):
            self.client.username_pw_set(config["username"], config.get("password"))

        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

    def connect(self):
        broker = self.config["broker"]
        port = int(self.config.get("port", 1883))
        self.client.connect(broker, port, keepalive=60)
        self.client.loop_start()
        logger.info(f"MQTT connecting to {broker}:{port}")

    def disconnect(self):
        self.client.loop_stop()
        self.client.disconnect()

    def publish_status(self, camera_name: str, state: str):
        topic = f"{BASE_TOPIC}/{camera_name}/status"
        self.client.publish(topic, state, retain=True)
        logger.debug(f"MQTT → {topic}: {state}")

    def publish_discovery(self):
        for camera_name in self.streams:
            self._publish_camera_discovery(camera_name)

    # ─── callbacks ────────────────────────────────────────────────────────────

    def _on_connect(self, client, userdata, flags, rc):
        if rc != 0:
            logger.error(f"MQTT connect failed (rc={rc})")
            return
        logger.info("MQTT connected")
        for camera_name in self.streams:
            client.subscribe(f"{BASE_TOPIC}/{camera_name}/start/set")
            client.subscribe(f"{BASE_TOPIC}/{camera_name}/stop/set")
        self.publish_discovery()
        # Sync current state to broker on (re)connect
        for camera_name in self.streams:
            st = self.recorder.status(camera_name)
            self.publish_status(camera_name, st["state"])

    def _on_disconnect(self, client, userdata, rc):
        if rc != 0:
            logger.warning(f"MQTT disconnected unexpectedly (rc={rc}), will auto-reconnect")

    def _on_message(self, client, userdata, msg):
        topic = msg.topic
        for camera_name in self.streams:
            if topic == f"{BASE_TOPIC}/{camera_name}/start/set":
                logger.info(f"MQTT → start {camera_name}")
                self.recorder.start(camera_name)
                self.publish_status(camera_name, self.recorder.status(camera_name)["state"])
                return
            if topic == f"{BASE_TOPIC}/{camera_name}/stop/set":
                logger.info(f"MQTT → stop {camera_name}")
                self.recorder.stop(camera_name)
                self.publish_status(camera_name, self.recorder.status(camera_name)["state"])
                return

    # ─── HA discovery ─────────────────────────────────────────────────────────

    def _publish_camera_discovery(self, camera_name: str):
        display_name = camera_name.replace("_", " ").title()

        # One HA device per camera; groups the three entities together
        device = {
            "identifiers": [f"ssr_{camera_name}"],
            "name": f"SSR {display_name}",
            "manufacturer": "simple_stream_recorder",
            "model": "RTSP Recorder",
        }

        self._pub(
            f"{HA_PREFIX}/sensor/ssr_{camera_name}_status/config",
            {
                "name": f"{display_name} Status",
                "unique_id": f"ssr_{camera_name}_status",
                "state_topic": f"{BASE_TOPIC}/{camera_name}/status",
                "icon": "mdi:record-circle-outline",
                "device": device,
            },
        )

        self._pub(
            f"{HA_PREFIX}/button/ssr_{camera_name}_start/config",
            {
                "name": f"{display_name} Start Recording",
                "unique_id": f"ssr_{camera_name}_start",
                "command_topic": f"{BASE_TOPIC}/{camera_name}/start/set",
                "payload_press": "PRESS",
                "icon": "mdi:record",
                "device": device,
            },
        )

        self._pub(
            f"{HA_PREFIX}/button/ssr_{camera_name}_stop/config",
            {
                "name": f"{display_name} Stop Recording",
                "unique_id": f"ssr_{camera_name}_stop",
                "command_topic": f"{BASE_TOPIC}/{camera_name}/stop/set",
                "payload_press": "PRESS",
                "icon": "mdi:stop",
                "device": device,
            },
        )

        logger.info(f"HA discovery published for {camera_name}")

    def _pub(self, topic: str, payload: dict):
        self.client.publish(topic, json.dumps(payload), retain=True)
