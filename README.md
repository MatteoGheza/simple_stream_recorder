# simple_stream_recorder

A lightweight Flask-based service designed to manage, start, stop, and monitor live video stream recordings (e.g., RTSP security cameras). It includes optional MQTT integration for real-time status updates and requires Bearer token authentication for all API endpoints.

---

## Features

* **Stream Management:** Easily start, stop, and check the status of specific camera streams via a REST API.
* **MQTT Integration:** Optionally publishes camera state changes to an MQTT broker.
* **Secure Endpoints:** Built-in Bearer token authentication to prevent unauthorized control.
* **Graceful Shutdown:** Auto-stops all active recordings and cleanly disconnects from MQTT on application exit.

---

## Configuration

The application expects a `config.yaml` file in the root directory. Copy the template below and adjust it to your setup:

```yaml
streams:
  camera_one:
    path: "rtsp://admin:admin@192.168.166.42:554/main/av"
  camera_two:
    path: "rtsp://admin:admin@192.168.166.43:554/main/av"

api:
  token: YOUR_SECRET_BEARER_TOKEN

mqtt:
  broker: 192.168.1.10   # Leave blank or omit to disable MQTT
  port: 1883
  username: ""
  password: ""

recording:
  path: /media

```

---

## Installation & Setup

1. **Clone the repository:**
```bash
git clone <repository-url>
cd simple_stream_recorder

```


2. **Install dependencies:**
Make sure you have your virtual environment active, then install the required packages:
```bash
pip install flask pyyaml

```


*(Note: Ensure your underlying `recorder` and `mqtt_client` modules are in the same directory or installed in your environment).*
3. **Run the application:**
```bash
python main.py

```


The service binds to `0.0.0.0` on port `5000` by default.

---

## API Documentation

All requests require the `Authorization` header populated with your configured token:
`Authorization: Bearer <YOUR_SECRET_BEARER_TOKEN>`

### 1. Start Recording

Starts recording the specified camera stream.

* **URL:** `/<camera_name>/start`
* **Method:** `POST`
* **Success Response:** `200 OK` with JSON response from the recorder.

### 2. Stop Recording

Stops recording the specified camera stream.

* **URL:** `/<camera_name>/stop`
* **Method:** `POST`
* **Success Response:** `200 OK` with JSON response from the recorder.

### 3. Get Stream Status

Retrieves current recording state and metadata for the camera.

* **URL:** `/<camera_name>/status`
* **Method:** `GET`
* **Success Response:** `200 OK` with status data.

### Error Codes

* `401 Unauthorized`: Missing or incorrect `Authorization` header.
* `404 Not Found`: The requested `camera_name` does not exist in `config.yaml`.
