import os, time, json, logging, sys
from copy import deepcopy

from paho.mqtt import client as mqtt_client
from ntfpy import NTFYServer, NTFYClient, NTFYPushMessage, NTFYUrlAttachment, NTFYUser
from paho.mqtt.enums import CallbackAPIVersion

MQTT_BROKER_IP = os.getenv("MQTT_BROKER_IP", "eclipse-mosquitto")
MQTT_BROKER_PORT = int(os.getenv("MQTT_BROKER_PORT", 1883))
MQTT_CLIENT_ID = os.getenv("MQTT_CLIENT_ID", "frigate-mqtt-notifier")
MQTT_BROKER_USERNAME = os.getenv("MQTT_BROKER_USERNAME")
MQTT_BROKER_PASSWORD = os.getenv("MQTT_BROKER_PASSWORD")

NTFY_SERVER_URL = os.getenv("NTFY_SERVER_URL", "https://ntfy.sh")
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "frigate-events")
NTFY_USERNAME = os.getenv("NTFY_USERNAME")
NTFY_PASSWORD = os.getenv("NTFY_PASSWORD")

MESSAGE_TIMEOUT = float(os.getenv("MESSAGE_TIMEOUT", 1.0))
FRIGATE_BASE_URL = os.getenv("FRIGATE_BASE_URL", "http://frigate:5000")

_last_msg_time = 0.0
_seen_new = {}
_entered_zones = {}

logging_levels = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "ERROR": logging.ERROR,
    "WARNING": logging.WARNING,
}

logging.basicConfig(level=logging_levels.get(os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO), format='%(asctime)s %(name)s %(levelname)s: %(message)s')

logging.info("Starting Frigate MQTT Notifier...")

logging.info("")
logging.info("FRIGATE MQTT NOTIFIER CONFIG:")
logging.info("")
logging.info(f"MQTT_BROKER_IP={MQTT_BROKER_IP}")
logging.info(f"MQTT_BROKER_PORT={MQTT_BROKER_PORT}")
logging.info(f"MQTT_CLIENT_ID={MQTT_CLIENT_ID}")
logging.info(f"MQTT_BROKER_USERNAME={MQTT_BROKER_USERNAME}")
logging.info(f"MQTT_BROKER_PASSWORD={MQTT_BROKER_PASSWORD}")
logging.info(f"MESSAGE_TIMEOUT={MESSAGE_TIMEOUT}")
logging.info(f"FRIGATE_BASE_URL={FRIGATE_BASE_URL}")
logging.info(f"NTFY_SERVER_URL={NTFY_SERVER_URL}")
logging.info(f"NTFY_TOPIC={NTFY_TOPIC}")
logging.info(f"NTFY_USERNAME={NTFY_USERNAME}")
logging.info(f"NTFY_PASSWORD={NTFY_PASSWORD}")
logging.info("")

logging.debug("Connecting to Ntfy...")

ntfy_server = NTFYServer(NTFY_SERVER_URL)
ntfy_user = NTFYUser(NTFY_USERNAME, NTFY_PASSWORD) if NTFY_USERNAME and NTFY_PASSWORD else None
ntfy_client = NTFYClient(ntfy_server, NTFY_TOPIC, ntfy_user)

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        logging.info("Connected to MQTT Broker!")

        msg = NTFYPushMessage(message="Connected to MQTT Broker!",title="Frigate MQTT Notifier")
        ntfy_client.send_message(msg)
    else:
        logging.error(f"Connection to MQTT Broker failed (rc={rc})")

        msg = NTFYPushMessage(message=f"Connection to MQTT Broker failed (rc={rc})",title="Frigate MQTT Notifier")
        ntfy_client.send_message(msg)

def get_zone_changes(event_id, current):
    prev = _entered_zones.setdefault(event_id, [])

    logging.debug(f"Event {event_id} previous zones: {', '.join(prev)}")
    logging.debug(f"Event {event_id} current zones: {', '.join(current)}")

    entered = [z for z in current if z not in prev]

    _entered_zones[event_id] = current.copy()

    logging.debug(f"Event {event_id} entered zones: {', '.join(entered)}")

    return entered

def on_message(client, userdata, mqtt_msg):
    global _last_msg_time
    now = time.time()

    if now - _last_msg_time < MESSAGE_TIMEOUT: # Throttle messages
        logging.debug("Event message throttled")
        return

    _last_msg_time = now

    try:
        payload = json.loads(mqtt_msg.payload)
    except json.JSONDecodeError:
        logging.warning("Invalid JSON payload got from MQTT broker")
        return

    event_type = payload.get("type")
    data = payload.get("after", {})
    eid = str(data.get("id", ""))

    if data.get("stationary"):
        logging.debug("Stationary event ignored")
        return

    label = data.get("label", "Object").capitalize()
    score = data.get("top_score", 0) * 100
    zones = data.get("current_zones", [])
    snap = data.get("has_snapshot")
    clip = data.get("has_clip")

    snap_url = f"{FRIGATE_BASE_URL}/api/events/{eid}/snapshot.jpg" if snap else None
    clip_url = f"{FRIGATE_BASE_URL}/api/events/{eid}/clip.mp4" if clip else None

    if event_type == "new":
        if not _seen_new.get(eid):
            _seen_new[eid] = True
            _entered_zones[eid] = deepcopy(zones)

            logging.debug(f"New {label} event detected in {', '.join(zones)}")

            body = f"New {label} Detected with {score:.1f}% certainty in {', '.join(zones)}"

            msg = NTFYPushMessage(body, title=f"{label} Detected")

            if clip_url:
                msg.attachment = NTFYUrlAttachment(clip_url)

                logging.debug(f"Found Event clip URL: {clip_url}")

            elif snap_url:
                msg.attachment = NTFYUrlAttachment(snap_url)

                logging.debug(f"Found Event snapshot URL: {snap_url}")

                ntfy_client.send_message(msg)

        else:
            logging.debug("Ignoring already seen event")

    elif event_type == "update":
        new_z = get_zone_changes(eid, zones)

        logging.debug(f"{label} event updated in {', '.join(zones)}")

        if not new_z:
            logging.debug(f"No new zones detected for event {eid}")
            return

        body = f"{label} entered zones: {', '.join(new_z)}"
        msg = NTFYPushMessage(body, title=f"{label} Zone Entry")

        if snap_url:
            msg.attachment = NTFYUrlAttachment(snap_url)

            logging.debug(f"Found Event snapshot URL: {snap_url}")

        ntfy_client.send_message(msg)

    elif event_type == "end":
        body = f"{label} left view"

        logging.debug(f"{label} event ended")

        msg = NTFYPushMessage(body, title=f"{label} Left View")

        if clip_url:
            msg.attachment = NTFYUrlAttachment(clip_url)

            logging.debug(f"Found Event clip URL: {clip_url}")

        elif snap_url:
            msg.attachment = NTFYUrlAttachment(snap_url)

            logging.debug(f"Found Event snapshot URL: {snap_url}")

        ntfy_client.send_message(msg)

client = mqtt_client.Client(CallbackAPIVersion.VERSION2, MQTT_CLIENT_ID)

if MQTT_BROKER_USERNAME:
    client.username_pw_set(MQTT_BROKER_USERNAME, MQTT_BROKER_PASSWORD)

client.on_connect = on_connect
client.on_message = on_message

try:
    client.connect(MQTT_BROKER_IP, MQTT_BROKER_PORT)
except Exception as e:
    logging.error(f"Failed to connect to MQTT broker: {e}")
    sys.exit(1)

try:
    client.subscribe("frigate/events")
except Exception as e:
    logging.error(f"Failed to subscribe to MQTT topic: {e}")
    sys.exit(1)

try:
    client.loop_forever()
except Exception as e:
    logging.error(f"Failed to start MQTT client: {e}")
    sys.exit(1)
