"""Home Assistant: Titel finden (REST über den Supervisor) und Sensoren per MQTT-Discovery anlegen."""

import json
import logging
import os
import re
import urllib.request

import paho.mqtt.client as mqtt

log = logging.getLogger("depot_daten.ha")
CORE = "http://supervisor/core/api"
SUP = "http://supervisor"
DISC = "homeassistant"
BASE_T = "depotdaten"
AVAIL = f"{BASE_T}/verfuegbar"
DEVICE = {"identifiers": ["depot_daten"], "name": "Depot-Daten", "manufacturer": "Eulerpool",
          "model": "Depot-Daten App", "sw_version": "0.2.0"}

TITLES_TEMPLATE = """{% set ns = namespace(o=[]) %}
{% for lab in LABELS %}{% for e in label_entities(lab) %}{% if e.startswith('sensor.') %}
{% set ns.o = ns.o + [{'entity': e, 'name': state_attr(e, 'friendly_name'), 'symbol': state_attr(e, 'symbol'),
  'long_name': state_attr(e, 'long_name'), 'currency': state_attr(e, 'currency'), 'price': states(e),
  'labels': labels(e)}] %}{% endif %}{% endfor %}{% endfor %}{{ ns.o | tojson }}"""


def slug(name):
    """Wie die Beobachtungslisten-Karte: klein, Leerzeichen → _ ; für Entitäts-IDs zusätzlich bereinigt."""
    s = (name or "").lower().replace(" ", "_")
    s = s.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    return re.sub(r"[^a-z0-9_]+", "", s).strip("_")


def _req(url, data=None, method=None, timeout=20):
    tok = os.environ.get("SUPERVISOR_TOKEN", "")
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method=method or ("POST" if body else "GET"),
                                 headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    try:
        return json.loads(raw)
    except ValueError:
        return raw.decode("utf-8", "replace")


def find_titles(labels):
    tpl = TITLES_TEMPLATE.replace("LABELS", json.dumps(labels))
    res = _req(f"{CORE}/template", {"template": tpl})
    if isinstance(res, str):
        res = json.loads(res)
    seen, out = set(), []
    for t in res:
        if t["entity"] in seen:
            continue
        seen.add(t["entity"])
        out.append(t)
    return out


def state_exists(entity_id):
    try:
        _req(f"{CORE}/states/{entity_id}")
        return True
    except Exception:
        return False


def delete_state(entity_id):
    """Entfernt einen Zustand ohne Registereintrag (Reste der Probe-Version 0.1)."""
    try:
        _req(f"{CORE}/states/{entity_id}", method="DELETE")
        return True
    except Exception:
        return False


def set_input_text(entity_id, value):
    try:
        _req(f"{CORE}/services/input_text/set_value", {"entity_id": entity_id, "value": value[:255]})
        return True
    except Exception as e:
        log.warning("%s: %s", entity_id, e)
        return False


def mqtt_credentials():
    d = _req(f"{SUP}/services/mqtt")
    return d.get("data", d)


class Mqtt:
    def __init__(self, on_command):
        c = mqtt_credentials()
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="depot_daten")
        if c.get("username"):
            self.client.username_pw_set(c["username"], c.get("password"))
        if c.get("ssl"):
            self.client.tls_set()
        self.client.will_set(AVAIL, "offline", retain=True)
        self.on_command = on_command
        self.client.on_connect = self._connected
        self.client.on_message = lambda cl, u, msg: self.on_command(msg.topic, msg.payload.decode("utf-8", "replace"))
        self.client.connect(c.get("host", "core-mosquitto"), int(c.get("port", 1883)), keepalive=60)
        self.client.loop_start()

    def _connected(self, client, userdata, flags, rc, props=None):
        log.info("MQTT verbunden (%s)", rc)
        client.publish(AVAIL, "online", retain=True)
        client.subscribe(f"{BASE_T}/befehl/#")
        client.subscribe(f"{DISC}/status")   # HA-Neustart → Discovery erneut senden

    def pub(self, topic, payload, retain=True):
        if not isinstance(payload, str):
            payload = json.dumps(payload, ensure_ascii=False, default=str)
        self.client.publish(topic, payload, qos=1, retain=retain)

    def sensor(self, key, name, icon, unit=None, device_class=None, state_class=None, attrs=True,
               entity_category=None, component="sensor", extra=None):
        cfg = {"name": name, "unique_id": f"depot_daten_{key}", "default_entity_id": f"{component}.depotdaten_{key}",
               "state_topic": f"{BASE_T}/{key}/state", "availability_topic": AVAIL, "icon": icon,
               "device": DEVICE}
        if attrs:
            cfg["json_attributes_topic"] = f"{BASE_T}/{key}/attr"
        if unit:
            cfg["unit_of_measurement"] = unit
        if device_class:
            cfg["device_class"] = device_class
        if state_class:
            cfg["state_class"] = state_class
        if entity_category:
            cfg["entity_category"] = entity_category
        if extra:
            cfg.update(extra)
        self.pub(f"{DISC}/{component}/depot_daten/{key}/config", cfg)

    def button(self, key, name, icon):
        cfg = {"name": name, "unique_id": f"depot_daten_{key}", "default_entity_id": f"button.depotdaten_{key}",
               "command_topic": f"{BASE_T}/befehl/{key}", "availability_topic": AVAIL, "icon": icon,
               "device": DEVICE}
        self.pub(f"{DISC}/button/depot_daten/{key}/config", cfg)

    def remove(self, key, component="sensor"):
        self.pub(f"{DISC}/{component}/depot_daten/{key}/config", "", retain=True)

    def state(self, key, value, attrs=None):
        self.pub(f"{BASE_T}/{key}/state", "None" if value is None else str(value))
        if attrs is not None:
            self.pub(f"{BASE_T}/{key}/attr", attrs)
