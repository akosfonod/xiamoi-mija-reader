import sys
from bluepy.btle import UUID, Peripheral, Characteristic, BTLEDisconnectError
import logging
import json
from influxdb import InfluxDBClient
import time

global connections
connections = []


def configure_logger(config):
    log_formatter = logging.Formatter('%(asctime)s : %(levelname)s : %(message)s')

    root_logger = logging.getLogger()
    try:
        root_logger.setLevel(logging.getLevelName(config['log_level']))
    except ValueError:
        print('Log level can not be set to {}, check the config file. Default: "INFO".'.format(config['log_level']))
        root_logger.setLevel(logging.INFO)


    file_Handler = logging.FileHandler(config['log_file'],mode="w+")
    if config['log_file_method'] == "append":
        file_Handler = logging.FileHandler(config['log_file'],mode="a")
    elif config['log_file_method'] == "overwrite":
        file_Handler = logging.FileHandler(config['log_file'],mode="w+")
    else:
        print('"log_file_method" in config json is invalid, options[overwrite,append]. Default mode: overwrite')

    file_Handler.setFormatter(log_formatter)
    root_logger.addHandler(file_Handler)

    console_Handler = logging.StreamHandler()
    console_Handler.setFormatter(log_formatter)
    root_logger.addHandler(console_Handler)

    return root_logger

def read_config(config_path):
    try:
        with open(config_path) as config_json:
            config = json.load(config_json)
            return config
    except FileNotFoundError as error:
        print("Could not find the file: " + config_path)
        sys.exit()
    except json.decoder.JSONDecodeError as error:
        print("Please check " + config_path + " file for formatting issues.")
        print(error)
        sys.exit()

def initialize_db_connection(config,logger):
    db_name = config['database']['name']
    host = config['database']['host']
    port = config['database']['port']

    try:
        client = InfluxDBClient(host=host,port=port)
        client.create_database(db_name)
        client.switch_database(db_name)
    except:
        logger.error('Could not connect to %s:%s', host, port)
        sys.exit()

    
    logger.info('Connection established to %s DB on %s:%s', db_name, host, port)

    return client

def handle_connections(config, logger):
    if connections is None:
        for device in config['devices']:
            try:
                mac_address = config['devices'][device]['mac_address']
                p = Peripheral(deviceAddr=mac_address,addrType='public')
                connections.append(p)
            except Exception as e:
                logger.error("Could not connect to: %s@%s", str(mac_address), device)
                logger.error(e)
                continue
    else:
        for device in config['devices']:
            connected = False
            for connection in connections:
                if connection.addr == config['devices'][device]['mac_address']: #Device found among active connections
                    connected = True

            if not connected: #Device has no active connection.
                try:
                    mac_address = config['devices'][device]['mac_address']
                    p = Peripheral(deviceAddr=mac_address,addrType='public')
                    connections.append(p)
                except Exception as e:
                    logger.error("Could not connect to: %s@%s. Removing it from connectinos.", str(mac_address), device)

def main():
    config = read_config('/xiaomi/config/config.json')
    logger = configure_logger(config)
    client = initialize_db_connection(config=config, logger=logger)

    uuid_characteristic_temperature_fine    = UUID("00002a6e-0000-1000-8000-00805f9b34fb") #handle 21
    uuid_characteristic_temperature_coarse  = UUID("00002a1f-0000-1000-8000-00805f9b34fb") #handle 18
    uuid_characteristic_humidity            = UUID("00002a6f-0000-1000-8000-00805f9b34fb") #handle 24
    uuid_characteristic_battery             = UUID("00002a19-0000-1000-8000-00805f9b34fb") #handle 14

    while True:
        handle_connections(config=config, logger=logger)

        if connections is not None:
            for connection in connections:
                try:
                    characteristics = connection.getCharacteristics()
                except BTLEDisconnectError as e:
                    logger.warning("%s device is not connected", connection.addr)
                    connections.remove(connection)#Remove disconnected device
                    continue

                for p in config['devices']:
                    if connection.addr is config['devices'][p]['mac_address']:
                        perip = p

                values = []

                for characteristic in characteristics:
                    if characteristic.uuid == uuid_characteristic_temperature_coarse:
                        values.insert(0, int.from_bytes(characteristic.read(),byteorder="little")/10)
                    if characteristic.uuid == uuid_characteristic_humidity:
                        values.insert(1, int.from_bytes(characteristic.read(),byteorder="little")/100)
                    if characteristic.uuid == uuid_characteristic_battery:
                        values.insert(2, int.from_bytes(characteristic.read(),byteorder="little"))

                logger.debug("Temp: %sC°\tHum: %s%%\tBat: %s%%\t%s\t%s", str(values[0]), str(values[1]), str(values[2]), connection.addr, perip)

                data_entry = [
                    {
                        "measurement": perip,
                        "fields":{
                            "temperature" : values[0],
                            "humidity"    : values[1],
                            "battery"     : values[2]
                        }
                    }
                ]
                #print (data_entry)

                if client.write_points(data_entry) is True:
                    logger.debug('SENT')

                values.clear()
        logger.debug('Active connections: %s', len(connections))
        #time.sleep(config['update_time']*60)
        time.sleep(config['update_time']*60)

if __name__ == "__main__":
    main()