"""Module containing a ThermostatClient for the Netatmo API."""

from __future__ import annotations

import json
from dataclasses import dataclass

from contextlib import asynccontextmanager
from datetime import datetime, time
from enum import Enum
from typing import AsyncGenerator, Callable

from httpx import AsyncClient

from .base import BaseClient
from .errors import NonOkResponseException, UnsuportedArgumentsException
from .thermostat_auth import ThermostatAuth
from .time import now
from .token import Token, TokenStore

_GET_THERMOSTATS_DATA_PATH = "api/getthermostatsdata"
_GET_MEASURE_PATH = "api/getmeasure"
_SET_SYSTEM_MODE_PATH = "api/setsystemmode"
_SET_MINOR_MODE_PATH = "api/setminormode"
_SYNC_SCHEDULE_PATH = "api/syncschedule"
_SWITCH_SCHEDULE_PATH = "api/switchschedule"
_SET_HOT_WATER_TEMPERATURE_PATH = "api/sethotwatertemperature"
_MODIFY_DEVICE_PARAM_PATH = "api/modifydeviceparam"
_SET_STATE_PATH = "syncapi/v1/setstate"
_GET_HOME_DATA_PATH = "api/homesdata"
_VAILLANT_DEVICE_TYPE = "NAVaillant"
_VAILLANT_DATA_AMOUNT = "app"
_VAILLANT_SYNC_DEVICE_ID = "all"
_RESPONSE_STATUS_OK = "ok"
_SETPOINT_DEFAULT_DURATION_MINS = 120


@dataclass
class HomeInfo:
    """Home information containing IDs needed for thermostat control."""
    home_id: str
    home_name: str
    rooms: list["RoomInfo"]
    modules: list["ModuleInfo"]

@dataclass
class RoomInfo:
    """Room information with room ID."""
    room_id: str
    room_name: str
    room_type: str
    room_module_id: str
    room_device_id: str

@dataclass
class ModuleInfo: 
    """Module information with module ID."""
    module_id: str
    module_name: str
    module_type: str
    room_id: str | None = None
    dhw_enabled: bool = False


@asynccontextmanager
async def thermostat_client(
    client_id: str,
    client_secret: str,
    token: Token,
    on_token_update: Callable[[Token], None],
) -> AsyncGenerator[ThermostatClient, None]:
    client = AsyncClient()
    token_store = TokenStore(client_id, client_secret, token, on_token_update)

    c = ThermostatClient(client, token_store)

    try:
        yield c
    finally:
        await client.aclose()


class ThermostatClient(BaseClient):
    """
    Client for making HTTP requests to the Netatmo API. Used for the subset of the API related to thermostats: getting thermostat data and changing thermostat modes.

    Uses BaseClient as a basis for making HTTP requests.
    """

    def __init__(
        self,
        client: AsyncClient,
        token_store: TokenStore,
    ) -> None:
        """
        Create new thermostat client instance.

        Uses the provided parameters to instantiate the BaseClient class.
        """

        super().__init__(client, ThermostatAuth(token_store))

    async def async_get_thermostats_data(self) -> list[Device]:
        """
        Get thermostat data from the Netatmo API.

        On success, returns a list of thermostat devices with their modules. On error, throws an exception.
        """

        path = _GET_THERMOSTATS_DATA_PATH
        data = {
            "device_type": _VAILLANT_DEVICE_TYPE,
            "data_amount": _VAILLANT_DATA_AMOUNT,
            "sync_device_id": _VAILLANT_SYNC_DEVICE_ID,
        }

        body = await self._post(
            path,
            data=data,
        )

        if body["status"] != _RESPONSE_STATUS_OK:
            raise NonOkResponseException(
                "Unknown response error. Check the log for more details.", path=path, data=data, body=body
            )

        return [Device(**device) for device in body["body"]["devices"]]

    async def async_get_measure(
        self,
        device_id: str,
        module_id: str,
        type: MeasurementType,
        scale: MeasurementScale,
        date_begin: datetime,
        date_end: datetime | None = None,
        limit: int | None = None,
    ) -> list[MeasurementItem]:
        """
        Get real time measurement data from the Netatmo API.

        On success, returns a list of measurements for provided measurement type. On error, throws an exception.
        """

        path = _GET_MEASURE_PATH
        data = {
            "device_id": device_id,
            "module_id": module_id,
            "type": type.value,
            "scale": scale.value,
            "date_begin": round(date_begin.timestamp()),
        }

        if date_end is not None:
            data["date_end"] = round(date_end.timestamp())
        if limit is not None:
            data["limit"] = limit

        body = await self._post(
            path,
            data=data,
        )

        if body["status"] != _RESPONSE_STATUS_OK:
            raise NonOkResponseException(
                "Unknown response error. Check the log for more details.", path=path, data=data, body=body
            )

        return [
            MeasurementItem(**measurement)
            for measurement in body["body"]
        ]

    async def async_set_system_mode(
        self, device_id: str, module_id: str, system_mode: SystemMode
    ) -> None:
        """
        Change the thermostat's system mode to the provided value.

        On success, returns nothing. On error, throws an exception.
        """

        path = _SET_SYSTEM_MODE_PATH
        data = {
            "device_id": device_id,
            "module_id": module_id,
            "system_mode": system_mode.value,
        }

        body = await self._post(
            path,
            data=data,
        )

        if body["status"] != _RESPONSE_STATUS_OK:
            raise NonOkResponseException(
                "Unknown response error. Check the log for more details.", path=path, data=data, body=body
            )

    async def async_set_minor_mode(
        self,
        device_id: str,
        module_id: str,
        setpoint_mode: SetpointMode,
        activate: bool,
        setpoint_endtime: datetime | None = None,
        setpoint_temp: float | None = None,
    ) -> None:
        """
        Activate or deactivate thermostat's minor mode, for the provided duration and temperature.

        On success, returns nothing. On error, throws an exception.
        """

        path = _SET_MINOR_MODE_PATH
        data = {
            "device_id": device_id,
            "module_id": module_id,
            "setpoint_mode": setpoint_mode.value,
            "activate": activate,
        }

        endtime = self._get_setpoint_endtime(
            setpoint_mode, activate, setpoint_endtime
        )
        if endtime is not None:
            data["setpoint_endtime"] = endtime

        temp = self._get_setpoint_temp(setpoint_mode, activate, setpoint_temp)
        if temp is not None:
            data["setpoint_temp"] = temp

        body = await self._post(
            path,
            data=data,
        )

        if body["status"] != _RESPONSE_STATUS_OK:
            raise NonOkResponseException(
                "Unknown response error. Check the log for more details.", path=path, data=data, body=body
            )
        
    async def async_set_state_room(
        self,
        home_id: str,
        room_id: str,
        setpoint_mode: SetpointMode,
        activate: bool,
        setpoint_endtime: datetime | None = None,
        setpoint_temp: float | None = None,
    ) -> None:
        """
        calling set_state
        Activate or deactivate thermostat's minor mode, for the provided duration and temperature.
        
        On success, returns nothing. On error, throws an exception.
        """
        
        path_json = _SET_STATE_PATH
        data_json = {
            "home": {
                "id": home_id,
                "rooms": [
                {
                   "id": room_id,
                   "therm_setpoint_mode": "manual",
                   "therm_setpoint_temperature": setpoint_temp,
                }
                ]
            }
        }
        
        endtime = self._get_setpoint_endtime(
            setpoint_mode, activate, setpoint_endtime
        )
        if endtime is not None:
            data_json["home"]["rooms"][0]["therm_setpoint_end_time"] = endtime
        
        body = await self._post(
            path_json,
            json=data_json,
        )
        
        if body["status"] != _RESPONSE_STATUS_OK:
            raise NonOkResponseException(
                "Unknown response error. Check the log for more details.", path=path_json, body=body, json=data_json
            )
    
    async def async_set_state_module(
        self,
        home_id: str,
        module_id: str,
        setpoint_mode: SetpointMode,
        activate: bool,
        setpoint_endtime: datetime | None = None,
        setpoint_temp: float | None = None,
    ) -> None:
        """
        calling set_state
        Activate or deactivate module, used in first instance to control hwb
        
        On success, returns nothing. On error, throws an exception.
        """
        
        path_json = _SET_STATE_PATH
        data_json = {
            "home": {
                "id": home_id,
                "modules": [
                {
                   "id": module_id,
                   "dhw_enabled": activate
                }
                ]
            }
        }
        
        endtime = self._get_setpoint_endtime(
            setpoint_mode, activate, setpoint_endtime
        )
        # to be confirmed that therm_setpoint_end_time is the correct one
        if endtime is not None:
            data_json["home"]["modules"][0]["therm_setpoint_end_time"] = endtime

        body = await self._post(
            path_json,
            json=data_json,
        )

        if body["status"] != _RESPONSE_STATUS_OK:
            raise NonOkResponseException(
                "Unknown response error. Check the log for more details.", path=path_json, body=body, json=data_json
            )

    async def async_sync_schedule(
        self,
        device_id: str,
        module_id: str,
        schedule_id: str,
        name: str,
        zones: list[Zone],
        timetable: list[TimeSlot],
    ) -> None:
        """
        Change thermostat's schedule, by providing all the data for the given schedule. The method upserts all the schedule data, it
        does not diff the data. The suggested usage is to always read the schedule first and provide the changed schedule in full back.

        On success, returns nothing. On error, throws an exception.
        """

        path = _SYNC_SCHEDULE_PATH
        data = {
            "device_id": device_id,
            "module_id": module_id,
            "schedule_id": schedule_id,
            "name": name,
            "zones": json.dumps([{
                "id": zone.id,
                # TODO: Should this call include name?
                "temp": zone.temp,
                "hw": zone.hw,
            } for zone in zones]),
            "timetable": json.dumps([{
                "id": time_slot.id,
                "m_offset": time_slot.m_offset,
            } for time_slot in timetable]),
        }

        body = await self._post(
            path,
            data=data,
        )

        if body["status"] != _RESPONSE_STATUS_OK:
            raise NonOkResponseException(
                "Unknown response error. Check the log for more details.", path=path, data=data, body=body
            )

    async def async_switch_schedule(
        self,
        device_id: str,
        module_id: str,
        schedule_id: str,
    ) -> None:
        """
        Change the thermostat's active schedule to the provided value.

        On success, returns nothing. On error, throws an exception.
        """

        path = _SWITCH_SCHEDULE_PATH
        data = {
            "device_id": device_id,
            "module_id": module_id,
            "schedule_id": schedule_id,
        }

        body = await self._post(
            path,
            data=data,
        )

        if body["status"] != _RESPONSE_STATUS_OK:
            raise NonOkResponseException(
                "Unknown response error. Check the log for more details.", path=path, data=data, body=body
            )

    async def async_modify_device_params(
        self,
        device_id: str,
        setpoint_default_duration: int,
    ) -> None:
        """
        Modify the thermostat's default setpoint duration.

        On success, returns nothing. On error, throws an exception.
        """

        path = _MODIFY_DEVICE_PARAM_PATH
        data = {
            "device_id": device_id,
            "setpoint_default_duration": setpoint_default_duration,
        }

        body = await self._post(
            path,
            data=data,
        )

        if body["status"] != _RESPONSE_STATUS_OK:
            raise NonOkResponseException(
                "Unknown response error. Check the log for more details.", path=path, data=data, body=body
            )

    async def async_set_hot_water_temperature(
        self,
        device_id: str,
        dhw: int,
    ) -> None:
        """
        Update boilers's domestic hot water temperature to the provided value. Value should be in valid range which can be retrieved
        by calling /api/getthermostatsdata.

        On success, returns nothing. On error, throws an exception.
        """

        path = _SET_HOT_WATER_TEMPERATURE_PATH
        data = {
            "device_id": device_id,
            "dhw": dhw,
        }

        body = await self._post(
            path,
            data=data,
        )

        if body["status"] != _RESPONSE_STATUS_OK:
            raise NonOkResponseException(
                "Unknown response error. Check the log for more details.", path=path, data=data, body=body
            )

    async def async_get_home_data(self) -> list[HomeInfo]:
        """Get home data including HOME_ID, ROOM_ID, and HWB_ID (module IDs).
        
        Returns:
            List of HomeInfo objects containing all necessary IDs for thermostat control.
        """
        path = _GET_HOME_DATA_PATH
        
        body = await self._post(path, data={})
        
        if body["status"] != _RESPONSE_STATUS_OK:
            raise NonOkResponseException(
                "Unknown response error. Check the log for more details.", path=path, data={}, body=body
            )
        
        homes = []
        for home_data in body.get("body", {}).get("homes", []):
            # Get rooms from home.rooms
            rooms = []
            for room_data in home_data.get("rooms", []):
                if room_data.get("module_ids"):
                    rooms.append(RoomInfo(
                        room_id=room_data["id"],
                        room_name=room_data.get("name", f"Room {room_data['id']}"),
                        room_type=room_data.get("type", ""),
                        room_module_id=room_data.get("module_ids", "")[0],
                        room_device_id=room_data.get("therm_relay","")
                    ))
                else:
                    rooms.append(RoomInfo(
                        room_id=room_data["id"],
                        room_name=room_data.get("name", f"Room {room_data['id']}"),
                        room_type=room_data.get("type", ""),
                        room_module_id="",
                        room_device_id=""
                    ))

            # Get HWB modules from schedules > zones > modules where dhw_enabled=true
            modules = []
            hwb_modules_found = set()  # Avoid duplicates
            
            for schedule in home_data.get("schedules", []):
                for zone in schedule.get("zones", []):
                    for module_data in zone.get("modules", []):
                        if module_data.get("dhw_enabled", False):
                            module_id = module_data["id"]
                            if module_id not in hwb_modules_found:
                                # Get module name from home.modules if available
                                module_name = "Unknown HWB Module"
                                module_type = "Unknown"
                                for home_module in home_data.get("modules", []):
                                    if home_module["id"] == module_id:
                                        module_name = home_module.get("name", f"Module {module_id}")
                                        module_type = home_module.get("type", "Unknown")
                                        break
                                
                                modules.append(ModuleInfo(
                                    module_id=module_id,
                                    module_name=module_name,
                                    module_type=module_type,
                                    room_id=None,
                                    dhw_enabled=True
                                ))
                                hwb_modules_found.add(module_id)
            
            homes.append(HomeInfo(
                home_id=home_data["id"],
                home_name=home_data.get("name", "Unknown Home"),
                rooms=rooms,
                modules=modules
            ))
        
        return homes

    def _get_setpoint_endtime(
        self,
        setpoint_mode: SetpointMode,
        activate: bool,
        setpoint_endtime: datetime | None = None,
    ) -> int | None:
        if not activate:
            if setpoint_endtime is not None:
                raise UnsuportedArgumentsException(
                    "Provided arguments for setting endtime are not valid.", setpoint_mode=setpoint_mode, activate=activate, setpoint_endtime=setpoint_endtime
                )
            return None
        else:
            if setpoint_endtime is None:
                if setpoint_mode == SetpointMode.MANUAL or setpoint_mode == SetpointMode.HWB:
                    raise UnsuportedArgumentsException(
                        "Provided arguments for setting endtime are not valid.", setpoint_mode=setpoint_mode, activate=activate, setpoint_endtime=setpoint_endtime
                    )
                return None
            else:
                if setpoint_endtime <= now():
                    raise UnsuportedArgumentsException(
                        "Provided arguments for setting endtime are not valid.", setpoint_mode=setpoint_mode, activate=activate, setpoint_endtime=setpoint_endtime
                    )
                return round(setpoint_endtime.timestamp())

    def _get_setpoint_temp(
        self,
        setpoint_mode: SetpointMode,
        activate: bool,
        setpoint_temp: float | None = None,
    ) -> float | None:
        if not activate:
            if setpoint_temp is not None:
                raise UnsuportedArgumentsException(
                    "Provided arguments for setting temp are not valid.", setpoint_mode=setpoint_mode, activate=activate, setpoint_temp=setpoint_temp
                )
            return None
        else:
            if setpoint_temp is None:
                if setpoint_mode == SetpointMode.MANUAL:
                    raise UnsuportedArgumentsException(
                        "Provided arguments for setting temp are not valid.", setpoint_mode=setpoint_mode, activate=activate, setpoint_temp=setpoint_temp
                    )
                return None
            else:
                if setpoint_mode != SetpointMode.MANUAL:
                    raise UnsuportedArgumentsException(
                        "Provided arguments for setting temp are not valid.", setpoint_mode=setpoint_mode, activate=activate, setpoint_temp=setpoint_temp
                    )
                return setpoint_temp


class Device:
    """Device model representing a Vaillant boiler. Contains multiple modules."""

    def __init__(
        self,
        _id: str | None = None,
        type: str = "",
        station_name: str = "",
        firmware: int = 0,
        wifi_status: int = 0,
        dhw: float | None = None,
        dhw_max: float | None = None,
        dhw_min: float | None = None,
        setpoint_default_duration: int = _SETPOINT_DEFAULT_DURATION_MINS,
        outdoor_temperature: dict = {},
        system_mode: str | None = None,
        setpoint_hwb: dict = {},
        modules: list[dict] = [],
        **kwargs,
    ) -> None:
        """Create new device model."""

        self.id = _id
        self.type = type
        self.station_name = station_name
        self.firmware = firmware
        self.wifi_status = wifi_status
        self.dhw = dhw
        self.dhw_max = dhw_max
        self.dhw_min = dhw_min
        self.setpoint_default_duration = setpoint_default_duration
        self.outdoor_temperature = OutdoorTemperature(**outdoor_temperature)
        self.system_mode = SystemMode(system_mode)
        self.setpoint_hwb = Setpoint(**setpoint_hwb)
        self.modules = [Module(**module) for module in modules]

    def __eq__(self, other: Device):
        if not isinstance(other, Device):
            return False

        return (
            self.id == other.id
            and self.type == other.type
            and self.station_name == other.station_name
            and self.firmware == other.firmware
            and len(self.modules) == len(other.modules)
            and all([False for i, j in zip(self.modules, other.modules) if i != j])
        )


class Module:
    """Module model representing a Vaillant thermostat."""

    def __init__(
        self,
        _id: str | None = None,
        type: str = "",
        module_name: str = "",
        firmware: int = 0,
        rf_status: int = 0,
        battery_percent: int = 0,
        setpoint_away: dict = {},
        setpoint_manual: dict = {},
        therm_program_list: list[dict] = [],
        measured: dict = {},
        boiler_status: bool = False,
        **kwargs,
    ) -> None:
        """Create new module model."""

        self.id = _id
        self.type = type
        self.module_name = module_name
        self.firmware = firmware
        self.rf_status = rf_status
        self.battery_percent = battery_percent
        self.setpoint_away = Setpoint(**setpoint_away)
        self.setpoint_manual = Setpoint(**setpoint_manual)
        self.therm_program_list = [
            Program(**program) for program in therm_program_list]
        self.measured = Measured(**measured)
        self.boiler_status = boiler_status

    def __eq__(self, other: Module):
        if not isinstance(other, Module):
            return False

        return (
            self.id == other.id
            and self.type == other.type
            and self.module_name == other.module_name
            and self.firmware == other.firmware
        )


class Program:
    """Program attribute representing a schedule for a thermostat."""

    def __init__(
        self,
        program_id: str | None = None,
        zones: list[dict] = [],
        timetable: list[dict] = [],
        name: str = "",
        selected: bool = False,
        **kwargs,
    ) -> None:
        """Create new program model."""

        self.id = program_id
        self.zones = [Zone(**zone) for zone in zones]
        self.timetable = [TimeSlot(**time_slot) for time_slot in timetable]
        self.name = name
        self.selected = selected

    def get_active_zone(self) -> Zone | None:
        """Returns a currently active zone for a program."""

        zone_id = 0
        for time_slot in self.timetable:
            if not time_slot.is_already_started:
                break
            zone_id = time_slot.id

        for zone in self.zones:
            if zone.id == zone_id:
                return zone

        return None

    def get_timeslots_for_today(self) -> list[TimeSlot]:
        """
        Returns a list of time slots which are defined for today.
        """

        n = now()

        time_slots = []
        previous_time_slot_zone_id = 0
        for time_slot in self.timetable:
            if time_slot.day == n.weekday():
                if len(time_slots) == 0 and time_slot.time != time(0, 0):
                    time_slots.append(
                        TimeSlot(
                            previous_time_slot_zone_id,
                            time_slot.day * 1440,
                        )
                    )
                time_slots.append(time_slot)
            previous_time_slot_zone_id = time_slot.id

        return time_slots

class Zone:
    """Zone attribute representing a zone profile which defines how thermostat behaves in a given time slot."""

    def __init__(
        self,
        id: int | None = None,
        name: str = "",
        temp: float = 0.0,
        hw: bool = False,
        **kwargs,
    ) -> None:
        """Create new zone attribute."""

        self.id = id
        self.temp = temp
        self.hw = hw

        if name:
            self.name = name
        else:
            if id == 0:
                self.name = "Comfort"
            elif id == 1:
                self.name = "Night"
            elif id == 2:
                self.name = "Away"
            elif id == 3:
                self.name = "Off"
            elif id == 4:
                self.name = "Eco"
            else:
                self.name = ""


class TimeSlot:
    """TimeSlot attribute representing one slot of a timetable schedule."""

    def __init__(
        self,
        id: int | None = None,
        m_offset: int = 0,
        **kwargs,
    ) -> None:
        """Create new time slot attribute."""

        self.id = id
        self.m_offset = m_offset

    @property
    def time(self) -> time:
        """Returns time instance representing the offset defined for this time slot."""

        daily_offset = self.m_offset % 1440

        return time(daily_offset // 60, daily_offset % 60)

    @property
    def day(self) -> int:
        """Returns a day for which this time slot is defined, using the same format as datetime.weekday()."""

        return self.m_offset // 1440

    @property
    def is_already_started(self) -> bool:
        n = now()

        if self.day < n.weekday():
            return True
        elif self.day == n.weekday() and self.time <= n.time():
            return True
        else:
            return False


class Setpoint:
    """Setpoint attribute representing a minor mode and its status."""

    def __init__(
        self,
        setpoint_activate: bool = False,
        setpoint_endtime: int | None = None,
        **kwargs,
    ) -> None:
        """Create new setpoint attribute."""

        self.setpoint_activate = setpoint_activate
        if setpoint_endtime is None:
            self.setpoint_endtime = None
        else:
            self.setpoint_endtime = datetime.fromtimestamp(setpoint_endtime)


class OutdoorTemperature:
    def __init__(
        self,
        te: float | None = None,
        ti: int | None = None,
        **kwargs,
    ) -> None:
        """Create new measured attribute."""

        self.te = te
        if ti is None:
            self.ti = None
        else:
            self.ti = datetime.fromtimestamp(ti)


class Measured:
    """Measured attribute representing a thermostat measurement."""

    def __init__(
        self,
        temperature: float | None = None,
        setpoint_temp: float | None = None,
        est_setpoint_temp: float | None = None,
        **kwargs,
    ) -> None:
        """Create new measured attribute."""

        self.temperature = temperature
        self.setpoint_temp = setpoint_temp
        self.est_setpoint_temp = est_setpoint_temp


class MeasurementItem:
    """MeasurementItem attribute representing a one measurement of thermostat module."""

    def __init__(
        self,
        beg_time: int | None = None,
        step_time: int | None = None,
        value: list[list[float]] = [],
        **kwargs,
    ) -> None:
        """Create new measurement item."""

        self.beg_time = beg_time
        self.step_time = step_time
        self.value = [
            value_item for inner_list in value for value_item in inner_list
        ]

    def __eq__(self, other: MeasurementItem):
        if not isinstance(other, MeasurementItem):
            return False

        return (
            self.beg_time == other.beg_time
            and self.step_time == other.step_time
            and len(self.value) == len(other.value)
            and all([False for i, j in zip(self.value, other.value) if i != j])
        )


class SystemMode(Enum):
    """SystemMode enumeration representing possible system modes of the thermostat."""

    WINTER = "winter"
    SUMMER = "summer"
    FROSTGUARD = "frostguard"


class SetpointMode(Enum):
    """SetpointMode enumeration representing possible minor modes of the thermostat."""

    MANUAL = "manual"
    AWAY = "away"
    HWB = "hwb"


class MeasurementType(Enum):
    """MeasurementType enumeration representing possible measurements of the thermostat."""

    TEMPERATURE = "temperature"
    SETPOINT_TEMPERATURE = "sp_temperature"
    SUM_BOILER_ON = "sum_boiler_on"
    SUM_BOILER_OFF = "sum_boiler_off"

    SUM_ENERGY_GAS_HEATING = "sum_energy_gaz_heating"
    SUM_ENERGY_GAS_WATER = "sum_energy_gaz_hot_water"
    SUM_ENERGY_ELEC_HEATING = "sum_energy_elec_heating"
    SUM_ENERGY_ELEC_WATER = "sum_energy_elec_hot_water"


class MeasurementScale(Enum):
    """MeasurementScale enumeration representing possible scale options for measurements of the thermostat."""

    MAX = "max"
    FIVE_MINS = "5min"
    HALF_HOUR = "30min"
    HOUR = "1hour"
    THREE_HOURS = "3hours"
    SIX_HOURS = "6hours"
    DAY = "1day"
    WEEK = "1week"
    MONTH = "1month"
