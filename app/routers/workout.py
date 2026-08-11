from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import asyncio

from app.ble.client import FtmsRowerClient
from app.schemas import DeviceInfo, WorkoutStartRequest, WorkoutStatus
from app.services.workout_manager import workout_manager

router = APIRouter(prefix="/api/workout", tags=["workout"])


class ScanResponse(BaseModel):
    devices: list[DeviceInfo]


@router.get("/status", response_model=WorkoutStatus)
async def workout_status() -> WorkoutStatus:
    return workout_manager.status()


@router.post("/scan", response_model=ScanResponse)
async def scan_devices() -> ScanResponse:
    client = FtmsRowerClient(on_metrics=lambda _m: None)
    try:
        devices = await client.scan(timeout=6.0)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ScanResponse(devices=[DeviceInfo(**d) for d in devices])


@router.post("/start", response_model=WorkoutStatus)
async def start_workout(payload: WorkoutStartRequest) -> WorkoutStatus:
    try:
        return await workout_manager.start(
            user_id=payload.user_id,
            mode=payload.mode,
            device_address=payload.device_address,
            serial_port=payload.serial_port,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/serial-ports")
async def serial_ports() -> dict:
    try:
        from app.ble.usb_s4 import UsbRowerClient

        return {"ports": UsbRowerClient.list_ports()}
    except Exception as exc:  # noqa: BLE001
        return {"ports": [], "error": str(exc)}


@router.get("/usb-status")
async def usb_status() -> dict:
    """Prüfen, ob ein S4 per USB erreichbar ist."""
    try:
        from app.ble.usb_s4 import UsbRowerClient

        port = await asyncio.to_thread(UsbRowerClient.find_s4_port)
        return {"available": port is not None, "port": port}
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "port": None, "error": str(exc)}


@router.post("/stop", response_model=WorkoutStatus)
async def stop_workout() -> WorkoutStatus:
    return await workout_manager.stop()


@router.post("/timer/start", response_model=WorkoutStatus)
async def timer_start() -> WorkoutStatus:
    return await workout_manager.timer_start()


@router.post("/timer/pause", response_model=WorkoutStatus)
async def timer_pause() -> WorkoutStatus:
    return await workout_manager.timer_pause()


@router.post("/timer/reset", response_model=WorkoutStatus)
async def timer_reset() -> WorkoutStatus:
    return await workout_manager.timer_reset()
