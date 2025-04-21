A docker container/Python app that watches for MQTT Frigate events and sends them to an Ntfy server.

To deploy it, you can use the official image:
```yaml
services:
  frigate-mqtt-notifier:
    image: csd4ni3lofficial/frigate-mqtt-notifier:latest
    container_name: frigate-mqtt-notifier
    environment:
      - LOG_LEVEL=INFO
      - MQTT_BROKER_IP=eclipse-mosquitto
      - MQTT_BROKER_PORT=1883
      - MQTT_CLIENT_ID=frigate-mqtt-notifier
      - MQTT_BROKER_USERNAME=
      - MQTT_BROKER_PASSWORD=
      - MESSAGE_TIMEOUT=5
      - FRIGATE_BASE_URL=http://frigate:5000
      - NTFY_SERVER_URL=https://ntfy.sh
      - NTFY_TOPIC=frigate-events
      - NTFY_USERNAME=
      - NTFY_PASSWORD=
    restart: unless-stopped
```
