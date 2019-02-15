import json
import logging

import voluptuous as vol
from homeassistant.helpers import config_validation as cv

from homeassistant.components.http import HomeAssistantView
from homeassistant.const import (MAJOR_VERSION, MINOR_VERSION)
from homeassistant.auth.const import ACCESS_TOKEN_EXPIRATION
import homeassistant.auth.models as models
from typing import Optional
from datetime import timedelta
from homeassistant.helpers.state import AsyncTrackStates
from urllib.request import urlopen

from .util import (decrypt_device_id,encrypt_entity_id)
import copy

_LOGGER = logging.getLogger(__name__)
# _LOGGER.setLevel(logging.DEBUG)

AI_HOME = True
DOMAIN       = 'aligenie'

_places       = []
_aliases      = []

async def async_setup(hass, config):
    hass.http.register_view(AliGenieGateView(hass))
    global _places, _aliases
    _places  = json.loads(urlopen('https://open.bot.tmall.com/oauth/api/placelist').read().decode('utf-8'))['data']
    _aliases = json.loads(urlopen('https://open.bot.tmall.com/oauth/api/aliaslist').read().decode('utf-8'))['data']
    _aliases.append({'key': '电视', 'value': ['电视机']})
    return True

class AliGenieGateView(HomeAssistantView):
    """View to handle Configuration requests."""

    url = '/aligenie_gate'
    name = 'aligenie_gate'
    # requires_auth = True    # 使用request头验证token

    def __init__(self, hass):
        """Initialize the token view."""
        self._aligenie = Aligenie(hass)
    async def post(self, request):
        """Update state of entity."""
        _LOGGER.debug('request: %s', request)
        try:
            data = await request.json()
            response = await self._aligenie.handleRequest(data)
        except:
            import traceback
            _LOGGER.error(traceback.format_exc())
            response = {}
        return self.json(response)
        
def createHandler(hass):
    return Aligenie(hass)

class Aligenie:
    def __init__(self, hass):
        self._hass = hass
        self._DEVICE_TYPES = {
            'television': '电视',
            'light': '灯',
            'aircondition': '空调',
            'airpurifier': '空气净化器',
            'outlet': '插座',
            'switch': '开关',
            'roboticvacuum': '扫地机器人',
            'curtain': '窗帘',
            'humidifier': '加湿器',
            'fan': '风扇',
            'bottlewarmer': '暖奶器',
            'soymilkmaker': '豆浆机',
            'kettle': '电热水壶',
            'watercooler': '饮水机',
            'cooker': '电饭煲',
            'waterheater': '热水器',
            'oven': '烤箱',
            'waterpurifier': '净水器',
            'fridge': '冰箱',
            'STB': '机顶盒',
            'sensor': '传感器',
            'washmachine': '洗衣机',
            'smartbed': '智能床',
            'aromamachine': '香薰机',
            'window': '窗',
            'kitchenventilator': '抽油烟机',
            'fingerprintlock': '指纹锁',
            'telecontroller': '万能遥控器',
            'dishwasher': '洗碗机',
            'dehumidifier': '除湿机',
        }

        self._INCLUDE_DOMAINS = {
            'climate': 'aircondition',
            'fan': 'fan',
            'light': 'light',
            'media_player': 'television',
            'remote': 'telecontroller',
            'switch': 'switch',
            'vacuum': 'roboticvacuum',
            }

        self._EXCLUDE_DOMAINS = [
            'automation',
            'binary_sensor',
            'device_tracker',
            'group',
            'zone',
            ]

        self._ALL_ACTIONS = [
            'TurnOn',
            'TurnOff',
            'SelectChannel',
            'AdjustUpChannel',
            'AdjustDownChannel',
            'AdjustUpVolume',
            'AdjustDownVolume',
            'SetVolume',
            'SetMute',
            'CancelMute',
            'Play',
            'Pause',
            'Continue',
            'Next',
            'Previous',
            'SetBrightness',
            'AdjustUpBrightness',
            'AdjustDownBrightness',
            'SetTemperature',
            'AdjustUpTemperature',
            'AdjustDownTemperature',
            'SetWindSpeed',
            'AdjustUpWindSpeed',
            'AdjustDownWindSpeed',
            'SetMode',
            'SetColor',
            'OpenFunction',
            'CloseFunction',
            'Cancel',
            'CancelMode']


        self._TRANSLATIONS = {
            'cover': {
                'TurnOn':  'open_cover',
                'TurnOff': 'close_cover'
            },
            'vacuum': {
                'TurnOn':  'start',
                'TurnOff': 'return_to_base'
            },
            'light': {
                'TurnOn':  'turn_on',
                'TurnOff': 'turn_off',
                'SetBrightness':        lambda state, payload: ('turn_on', {'brightness_pct': payload['value']}),
                'AdjustUpBrightness':   lambda state, payload: ('turn_on', {'brightness_pct': min(state.attributes['brightness_pct'] + payload['value'], 100)}),
                'AdjustDownBrightness': lambda state, payload: ('turn_on', {'brightness_pct': max(state.attributes['brightness_pct'] - payload['value'], 0)}),
                'SetColor':             lambda state, payload: ('turn_on', {"color_name": payload['value']})
            },

        }
    def _errorResult(self, errorCode, messsage=None):
        """Generate error result"""
        messages = {
            'INVALIDATE_CONTROL_ORDER':    'invalidate control order',
            'SERVICE_ERROR': 'service error',
            'DEVICE_NOT_SUPPORT_FUNCTION': 'device not support',
            'INVALIDATE_PARAMS': 'invalidate params',
            'DEVICE_IS_NOT_EXIST': 'device is not exist',
            'IOT_DEVICE_OFFLINE': 'device is offline',
            'ACCESS_TOKEN_INVALIDATE': ' access_token is invalidate'
        }
        return {'errorCode': errorCode, 'message': messsage if messsage else messages[errorCode]}

    async def handleRequest(self, data, ignoreToken = False):
        """Handle request"""
        header = data['header']
        payload = data['payload']
        properties = None
        name = header['name']
        _LOGGER.info("Handle Request: %s", data)

        token = await self._hass.auth.async_validate_access_token(payload['accessToken'])
        if ignoreToken or token is not None:
            namespace = header['namespace']
            if namespace == 'AliGenie.Iot.Device.Discovery':
                result = self._discoveryDevice()
            elif namespace == 'AliGenie.Iot.Device.Control':
                result = await self._controlDevice(name, payload)
            elif namespace == 'AliGenie.Iot.Device.Query':
                result = self._queryDevice(name, payload)
                if not 'errorCode' in result:
                    properties = result
                    result = {}
            else:
                result = self._errorResult('SERVICE_ERROR')
        else:
            result = self._errorResult('ACCESS_TOKEN_INVALIDATE')

        # Check error and fill response name
        header['name'] = ('Error' if 'errorCode' in result else name) + 'Response'

        # Fill response deviceId
        if 'deviceId' in payload:
            result['deviceId'] = payload['deviceId']

        response = {'header': header, 'payload': result}
        if properties:
            response['properties'] = properties
        _LOGGER.info("Respnose: %s", response)
        return response

    def _discoveryDevice(self):

        states = self._hass.states.async_all()
        groups_ttributes = self._groupsAttributes(states)

        devices = []
        for state in states:
            attributes = state.attributes

            if attributes.get('hidden') or attributes.get('hagenie_hidden'):
                continue

            friendly_name = attributes.get('friendly_name')
            if friendly_name is None:
                continue
            entity_id = state.entity_id

            deviceType = self._guessDeviceType(entity_id, attributes)
            if deviceType is None:
                continue

            deviceName = self._guessDeviceName(entity_id, attributes, _places, _aliases)
            if deviceName is None:
                continue

            zone = self._guessZone(entity_id, attributes, groups_ttributes, _places)
            if zone is None:
                continue

            properties,actions = self._guessPropertyAndAction(entity_id, attributes, state.state)

            _LOGGER.debug('-----entity_id: %s, deviceType: %s, attributes: %s', entity_id, deviceType ,attributes)
            if deviceType == 'sensor':
                if attributes.get('aligenie_sensor_group') is None:
                    continue
                _LOGGER.debug('-----entity_id: %s, attributes: %s', entity_id, attributes)
                entity_ids = self._hass.states.get(attributes.get('aligenie_sensor_group')).attributes.get('entity_id')
                for sensor in entity_ids:
                    if sensor.startswith('sensor.'):
                        prop,action = self._guessPropertyAndAction(sensor, self._hass.states.get(sensor).attributes, self._hass.states.get(sensor).state)
                        actions += action
                        properties += prop
                actions = list(set(actions))

            devices.append({
                'deviceId': encrypt_entity_id(entity_id),
                'deviceName': deviceName,
                'deviceType': deviceType,
                'zone': zone,
                'model': friendly_name,
                'brand': 'HomeAssistant',
                'icon': 'https://d33wubrfki0l68.cloudfront.net/cbf939aa9147fbe89f0a8db2707b5ffea6c192cf/c7c55/images/favicon-192x192-full.png',
                'properties': properties if properties else [],
                'actions': actions,
                #'actions': ['TurnOn', 'TurnOff', 'Query', action] if action == 'QueryPowerState' else ['Query', action],
                #'extensions':{'extension1':'','extension2':''}
                })

        #for sensor in devices:
            #if sensor['deviceType'] == 'sensor':
                #_LOGGER.info(json.dumps(sensor, indent=2, ensure_ascii=False))
        return {'devices': devices}

    async def _controlDevice(self, cmnd, payload):
        entity_id = decrypt_device_id(payload['deviceId'])
        domain = entity_id[:entity_id.find('.')]
        data = {"entity_id": entity_id }
        if domain in self._TRANSLATIONS.keys():
            translation = self._TRANSLATIONS[domain][cmnd]
            if callable(translation):
                service, content = translation(self._hass.states.get(entity_id), payload)
                data.update(content)
            else:
                service = translation
        else:
            service = self._getControlService(cmnd)

        with AsyncTrackStates(self._hass) as changed_states:
            result = await self._hass.services.async_call(domain, service, data, True)

        return {} if result else self._errorResult('IOT_DEVICE_OFFLINE')

    def _queryDevice(self, cmnd, payload):
        entity_id = decrypt_device_id(payload['deviceId'])
        state = self._hass.states.get(entity_id)

        if entity_id.startswith('sensor.'):
            entity_ids = self._hass.states.get(state.attributes.get('aligenie_sensor_group')).attributes.get('entity_id')

            # properties = [{'name':'PowerState', 'value':'on'}]
            properties = []
            for entity_id in entity_ids:
                entity = self._hass.states.get(entity_id)
                if entity_id.startswith('sensor.') and entity.attributes.get('aligenie_sensor') is not None :
                    prop,action = self._guessPropertyAndAction(entity_id, entity.attributes, entity.state)
                    _LOGGER.debug('property:%s', prop)
                    if prop is None:
                        continue
                    elif prop[0].get('name').lower() in cmnd.lower():
                        properties = prop #单一状态直接返回，不适用数组
                        break
                    elif cmnd == 'Query':
                        properties += prop
            return properties if properties else self._errorResult('IOT_DEVICE_OFFLINE')
        else:
            if state is not None or state.state != 'unavailable':
                return {'name':'powerstate', 'value':state.state}
        return self._errorResult('IOT_DEVICE_OFFLINE')

    def _getControlService(self, action):
        i = 0
        service = ''
        for c in action:
            service += (('_' if i else '') + c.lower()) if c.isupper() else c
            i += 1
        return service



    # http://doc-bot.tmall.com/docs/doc.htm?treeId=393&articleId=108271&docType=1
    def _guessDeviceType(self, entity_id, attributes):
        if 'hagenie_deviceType' in attributes:
            return attributes['hagenie_deviceType']

        # Exclude with domain
        domain = entity_id[:entity_id.find('.')]
        if domain in self._EXCLUDE_DOMAINS:
            return None

        # Guess from entity_id
        for deviceType in self._DEVICE_TYPES.keys():
            if deviceType in entity_id:
                return deviceType

        # Map from domain
        return self._INCLUDE_DOMAINS[domain] if domain in self._INCLUDE_DOMAINS else None

    def _guessDeviceName(self, entity_id, attributes, places, aliases):
        if 'hagenie_deviceName' in attributes:
            return attributes['hagenie_deviceName']

        # Remove place prefix
        name = attributes['friendly_name']
        for place in places:
            if name.startswith(place):
                name = name[len(place):]
                break

        if aliases is None or entity_id.startswith('sensor'):
            return name

        # Name validation
        for alias in aliases:
            if name == alias['key'] or name in alias['value']:
                return name

        _LOGGER.error('%s is not a valid name in https://open.bot.tmall.com/oauth/api/aliaslist', name)
        return None

    def _groupsAttributes(self, states):
        groups_attributes = []
        for state in states:
            group_entity_id = state.entity_id
            if group_entity_id.startswith('group.') and not group_entity_id.startswith('group.all_') and group_entity_id != 'group.default_view':
                group_attributes = state.attributes
                if 'entity_id' in group_attributes:
                    groups_attributes.append(group_attributes)
        return groups_attributes

    # https://open.bot.tmall.com/oauth/api/placelist
    def _guessZone(self, entity_id, attributes, groups_attributes, places):
        if 'hagenie_zone' in attributes:
            return attributes['hagenie_zone']

        # Guess with friendly_name prefix
        name = attributes['friendly_name']
        for place in places:
            if name.startswith(place):
                return place

        # Guess from HomeAssistant group
        for group_attributes in groups_attributes:
            for child_entity_id in group_attributes['entity_id']:
                if child_entity_id == entity_id:
                    if 'hagenie_zone' in group_attributes:
                        return group_attributes['hagenie_zone']
                    return group_attributes['friendly_name']

        return None

    def _guessPropertyAndAction(self, entity_id, attributes, state):
        # http://doc-bot.tmall.com/docs/doc.htm?treeId=393&articleId=108264&docType=1
        if 'aligenie_actions' in attributes:
            actions = copy.deepcopy(attributes['aligenie_actions']) # fix
        elif entity_id.startswith('switch.'):
            actions = ["TurnOn", "TurnOff"]
        elif entity_id.startswith('light.'):
            actions = ["TurnOn", "TurnOff", "SetBrightness", "AdjustUpBrightness", "AdjustDownBrightness", "setColor"]
        elif entity_id.startswith('cover.'):
            actions = ["TurnOn", "TurnOff", "Pause"]
        elif entity_id.startswith('vacuum.'):
            actions = ["TurnOn", "TurnOff"]
        elif entity_id.startswith('sensor.'):
            actions = ["Query"]
        else:
            actions = ["TurnOn", "TurnOff"]
    
        if 'hagenie_propertyName' in attributes:
            name = attributes['hagenie_propertyName']
        elif entity_id.startswith('sensor.'):
            unit = attributes['unit_of_measurement'] if 'unit_of_measurement' in attributes else ''
            if unit == u'°C' or unit == u'℃':
                name = 'Temperature'
            elif unit == 'lx' or unit == 'lm':
                name = 'Brightness'
            elif ('humidity' in entity_id):
                name = 'Humidity'
            elif ('pm25' in entity_id):
                name = 'PM2.5'
            elif ('co2' in entity_id):
                name = 'WindSpeed'
            else:
                name = None
        else:
            name = 'PowerState'
            if state != 'off':
                state = 'on'
        properties = []
        if name is not None:
            actions += ['Query'+name,]
            properties = [{'name': name.lower(), 'value': state}]
        return properties, actions