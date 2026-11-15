"""Evidence-first flight-controller identity extraction.

Board targets, retail controller models and aircraft models are different facts.
This module intentionally does not translate a firmware target into a product
name without a verified mapping.
"""

import os
import re


def _safe(value, limit=100):
    text = " ".join(str(value or "").split())
    text = re.sub(r"[\x00-\x1f\x7f]", "", text)
    return text[:limit]


def detect_log_format(path):
    """Check binary signatures instead of treating a filename as evidence."""
    with open(path, "rb") as source:
        head = source.read(16)
    if head.startswith(b"ULog\x01\x12\x35"):
        return "PX4 ULog"
    if head.startswith(b"\xa3\x95"):
        return "ArduPilot DataFlash"
    return "Delimited text or unsupported binary"


def extract_log_identity(path):
    """Return only identity claims that are backed by source-log fields."""
    extension = os.path.splitext(path)[1].lower()
    signature = detect_log_format(path)
    result = {
        "format": signature,
        "ecosystem": "Unknown",
        "board_target": None,
        "hardware_model": None,
        "aircraft_model": None,
        "firmware": None,
        "vehicle_type": None,
        "evidence": [],
        "limitations": [],
    }
    if extension == ".ulg":
        if signature != "PX4 ULog":
            raise ValueError("The .ulg file does not contain a PX4 ULog signature.")
        from pyulog import ULog
        log = ULog(path, message_name_filter_list=[])
        info = log.msg_info_dict
        result["ecosystem"] = "PX4"
        result["evidence"].append("ULog binary signature")
        for field, destination in (
            ("ver_hw", "board_target"),
            ("ver_sw", "firmware"),
        ):
            value = _safe(info.get(field))
            if value:
                result[destination] = value
                result["evidence"].append(f"ULog {field} = {value}")
        subtype = _safe(info.get("ver_hw_subtype"))
        if subtype:
            result["evidence"].append(f"ULog ver_hw_subtype = {subtype}")
        # SYS_AUTOSTART is an airframe configuration ID, not a retail model.
        airframe_id = log.initial_parameters.get("SYS_AUTOSTART")
        if airframe_id is not None:
            result["evidence"].append(
                f"PX4 SYS_AUTOSTART = {_safe(airframe_id)} (configuration ID)"
            )
    elif extension == ".bin":
        if signature != "ArduPilot DataFlash":
            raise ValueError("The .bin file does not contain an ArduPilot DataFlash signature.")
        from pymavlink import DFReader
        log = DFReader.DFReader_binary(path)
        result["ecosystem"] = "ArduPilot"
        result["evidence"].append("DataFlash binary signature")
        seen = set()
        while True:
            try:
                message = log.recv_match(type=["MSG", "PARM"], blocking=False)
            except Exception:
                break
            if message is None:
                break
            if message.get_type() == "MSG":
                banner = _safe(getattr(message, "Message", None))
                if not banner or banner in seen:
                    continue
                seen.add(banner)
                if re.match(r"^(APM:)?(?:ArduCopter|ArduPlane|ArduRover|Copter|Plane|Rover)\b", banner, re.I):
                    result["firmware"] = banner
                    result["evidence"].append(f"DataFlash MSG = {banner}")
                elif re.match(r"^(?:PX4v\d+|Cube\S*|Pixhawk\S*)\b", banner, re.I):
                    result["board_target"] = banner.split()[0]
                    # Remaining banner tokens can include a device identifier.
                    result["evidence"].append(
                        f"DataFlash MSG board target = {result['board_target']}"
                    )
                elif banner.startswith("Frame:"):
                    result["vehicle_type"] = _safe(banner[6:])
                    result["evidence"].append(f"DataFlash MSG = {banner}")
            elif getattr(message, "Name", None) == "BRD_TYPE":
                value = _safe(getattr(message, "Value", None))
                if value:
                    result["evidence"].append(
                        f"DataFlash PARM BRD_TYPE = {value} (code, not retail model)"
                    )
    elif extension in {".csv", ".txt"}:
        if signature != "Delimited text or unsupported binary":
            raise ValueError("The file extension does not match its binary log signature.")
        result["format"] = "CSV/TXT telemetry"
        result["limitations"].append(
            "A delimited export does not prove its original flight controller."
        )
    else:
        raise ValueError("Unsupported flight-log file type.")

    if not result["board_target"]:
        result["limitations"].append("No usable board target found in this log.")
    result["limitations"].append(
        "A board target does not establish the marketed controller or aircraft model."
    )
    return result
