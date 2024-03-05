#!/usr/bin/env python3

import paho.mqtt.client as mqtt
from meshtastic import mesh_pb2, mqtt_pb2, portnums_pb2
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
import base64
import random
import time
from plyer import notification

# Default settings
MQTT_BROKER = "mqtt.meshtastic.org"
MQTT_PORT = 1883
MQTT_USERNAME = "meshdev"
MQTT_PASSWORD = "large4cats"
root_topic = "msh/ANZ/2/c/"
channel = "LongFast"
key = "1PG7OiApB1nwvP+rz05pAQ=="

long_name_entry = "MQTT-PARROT"
# short_name_entry = "🦜"
short_name_entry = "\U0001F99C" # 🦜 emoji
client_hw_model = "PRIVATE_HW"

REPLY_DELAY = 1 # seconds

padded_key = key.ljust(len(key) + ((4 - (len(key) % 4)) % 4), '=')
replaced_key = padded_key.replace('-', '+').replace('_', '/')
key = replaced_key

broadcast_id = 4294967295

def create_node_id(node_number):
    return f"!{hex(node_number)[2:]}"

def decode_node_id(node_id):
    hex_string = node_id[1:]  # Removing the '!' character
    return int(hex_string, 16)

node_id = "!abcde1e2"
node_number = decode_node_id(node_id)


node_id = create_node_id(node_number)
node_name = node_id

print(f'AUTO-ROUTER NODE-ID: {node_id}')

def set_topic():
    global subscribe_topic, publish_topic, node_number, node_name
    node_name = '!' + hex(node_number)[2:]
    subscribe_topic = root_topic + channel + "/#"
    publish_topic = root_topic + channel + "/" + node_name

def current_time():
    current_time_seconds = time.time()
    current_time_struct = time.localtime(current_time_seconds)
    current_time_str = time.strftime("%H:%M:%S", current_time_struct)
    return(current_time_str)

def xor_hash(data):
    result = 0
    for char in data:
        result ^= char
    return result

def generate_hash(name, key):
    replaced_key = key.replace('-', '+').replace('_', '/')
    key_bytes = base64.b64decode(replaced_key.encode('utf-8'))
    h_name = xor_hash(bytes(name, 'utf-8'))
    h_key = xor_hash(key_bytes)
    result = h_name ^ h_key
    return result

def direct_message(destination_id):
    destination_id = int(destination_id[1:], 16)
    publish_message(destination_id)

def publish_message(destination_id, message):
    global key
    message_text = message
    if message_text:
        encoded_message = mesh_pb2.Data()
        encoded_message.portnum = portnums_pb2.TEXT_MESSAGE_APP 
        encoded_message.payload = message_text.encode("utf-8")

    generate_mesh_packet(destination_id, encoded_message)

def generate_mesh_packet(destination_id, encoded_message):
    mesh_packet = mesh_pb2.MeshPacket()

    setattr(mesh_packet, "from", node_number)
    mesh_packet.id = random.getrandbits(32)
    mesh_packet.to = destination_id
    mesh_packet.want_ack = False
    mesh_packet.channel = generate_hash(channel, key)
    mesh_packet.hop_limit = 3

    if key == "":
        mesh_packet.decoded.CopyFrom(encoded_message)
    else:
        mesh_packet.encrypted = encrypt_message(channel, key, mesh_packet, encoded_message)

    service_envelope = mqtt_pb2.ServiceEnvelope()
    service_envelope.packet.CopyFrom(mesh_packet)
    service_envelope.channel_id = channel
    service_envelope.gateway_id = node_name

    payload = service_envelope.SerializeToString()
    set_topic()
    client.publish(publish_topic, payload)

def encrypt_message(channel, key, mesh_packet, encoded_message):
    mesh_packet.channel = generate_hash(channel, key)
    key_bytes = base64.b64decode(key.encode('ascii'))
    nonce_packet_id = mesh_packet.id.to_bytes(8, "little")
    nonce_from_node = node_number.to_bytes(8, "little")
    nonce = nonce_packet_id + nonce_from_node

    cipher = Cipher(algorithms.AES(key_bytes), modes.CTR(nonce), backend=default_backend())
    encryptor = cipher.encryptor()
    encrypted_bytes = encryptor.update(encoded_message.SerializeToString()) + encryptor.finalize()

    return encrypted_bytes

known_id_list = []

parrot_emoji = "\U0001F99C"

def process_message(mp, text_payload, is_encrypted):
    mp_id = getattr(mp, "id")
    mp_to = getattr(mp, "to")
    mp_from = getattr(mp, "from")

    parrot_flag = False
    broadcast_flag = False
    direct_flag = False
    from_parrot = False

    if mp_from == node_number:
        print("Parrot message detected")
        from_parrot = True

    if mp_id not in known_id_list:
        known_id_list.append(mp_id)
        print(mp)

        if text_payload.startswith("\U0001F99C"):
            print("Parrot emoji detected! \U0001F99C")
            parrot_flag = True
        if mp_to == broadcast_id:
            print("broadcast message detected")
            broadcast_flag = True

        if create_node_id(getattr(mp, "to")) == node_id:
            direct_flag = True

        if direct_flag:
            time.sleep(REPLY_DELAY)
            publish_message(mp_from, f'PARROT:{text_payload}')

        if broadcast_flag and parrot_flag and not from_parrot:
            time.sleep(REPLY_DELAY)
            publish_message(broadcast_id, f'{parrot_emoji}')


def decode_encrypted(message_packet):
    try:
        key_bytes = base64.b64decode(key.encode('ascii'))
        nonce_packet_id = getattr(message_packet, "id").to_bytes(8, "little")
        nonce_from_node = getattr(message_packet, "from").to_bytes(8, "little")
        nonce = nonce_packet_id + nonce_from_node

        cipher = Cipher(algorithms.AES(key_bytes), modes.CTR(nonce), backend=default_backend())
        decryptor = cipher.decryptor()
        decrypted_bytes = decryptor.update(getattr(message_packet, "encrypted")) + decryptor.finalize()

        data = mesh_pb2.Data()
        data.ParseFromString(decrypted_bytes)
        message_packet.decoded.CopyFrom(data)
        
        if message_packet.decoded.portnum == portnums_pb2.TEXT_MESSAGE_APP:
            text_payload = message_packet.decoded.payload.decode("utf-8")
            is_encrypted = True
            process_message(message_packet, text_payload, is_encrypted)

    except Exception as e:
        print(e)
        pass

def send_node_info(destination_id):
    global client_short_name, client_long_name, node_name, node_number, client_hw_model, broadcast_id

    if not client.is_connected():
        print(current_time() + " >>> Connect to a broker before sending nodeinfo")
    else:
        node_number = int(node_number)

        decoded_client_id = bytes(node_name, "utf-8")
        decoded_client_long = bytes(long_name_entry, "utf-8")
        decoded_client_short = bytes(short_name_entry, "utf-8")
        decoded_client_hw_model = client_hw_model

        user_payload = mesh_pb2.User()
        setattr(user_payload, "id", decoded_client_id)
        setattr(user_payload, "long_name", decoded_client_long)
        setattr(user_payload, "short_name", decoded_client_short)
        setattr(user_payload, "hw_model", decoded_client_hw_model)

        user_payload = user_payload.SerializeToString()

        encoded_message = mesh_pb2.Data()
        encoded_message.portnum = portnums_pb2.NODEINFO_APP
        encoded_message.payload = user_payload
        encoded_message.want_response = True  # Request NodeInfo back

        generate_mesh_packet(destination_id, encoded_message)


def on_connect(client, userdata, flags, rc, properties):
    if rc == 0:
        print(f"Connected to {MQTT_BROKER} on topic {channel}")
        send_node_info(broadcast_id)
    else:
        print(f"Failed to connect to MQTT broker with result code {str(rc)}")

def on_message(client, userdata, msg):
    service_envelope = mqtt_pb2.ServiceEnvelope()
    
    try:
        service_envelope.ParseFromString(msg.payload)
        message_packet = service_envelope.packet
    except Exception as e:
        print(f"Error parsing message: {str(e)}")
        return
    
    if message_packet.HasField("encrypted") and not message_packet.HasField("decoded"):
        decode_encrypted(message_packet)

if __name__ == '__main__':
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

    client.on_connect = on_connect
    client.username_pw_set(username=MQTT_USERNAME, password=MQTT_PASSWORD)
    client.connect(MQTT_BROKER, MQTT_PORT, 60)

    client.on_message = on_message

    subscribe_topic = f"{root_topic}{channel}/#"
    client.subscribe(subscribe_topic, 0)

    while client.loop() == 0:
        pass
