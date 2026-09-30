"""Protocol collector — entry point.
Supervise les tasks BACnet (sniffer, worker) et fournit un heartbeat.
"""
from __future__ import annotations
import asyncio
import os
import traceback

from net_utils import list_interfaces
from bacnet_sniffer import run_sniffer
from bacnet_worker import run_worker

API_URL = os.getenv("API_URL", "http://api:8000")
INTERNAL_TOKEN = os.getenv("INTERNAL_TOKEN", "")
HEADERS = {"X-Internal-Token": INTERNAL_TOKEN} if INTERNAL_TOKEN else {}

BACNET_SNIFF_ENABLE = os.getenv("BACNET_SNIFF_ENABLE", "1") == "1"


async def supervised(name: str, coro_factory, state: dict):
    """Wrapper qui redémarre une task si elle plante, avec traceback complet."""
    while True:
        state[name] = "running"
        try:
            await coro_factory()
            state[name] = "ended (returned)"
            print(f"[{name}] terminé sans exception — redémarrage dans 5s", flush=True)
        except asyncio.CancelledError:
            state[name] = "cancelled"
            raise
        except Exception as exc:
            state[name] = f"error: {type(exc).__name__}"
            print(f"[{name}] EXCEPTION: {exc}", flush=True)
            traceback.print_exc()
        await asyncio.sleep(5)


async def heartbeat(state: dict):
    """Toutes les 30s, log l'état des tasks + compteurs."""
    while True:
        await asyncio.sleep(30)
        print(
            f"[heartbeat] sniffer={state.get('sniffer', '?')} "
            f"worker={state.get('worker', '?')} "
            f"frames={state.get('frames', 0)} "
            f"jobs_done={state.get('jobs_done', 0)}",
            flush=True,
        )


async def main():
    print("=" * 60, flush=True)
    print("[collector] protocol-collector — démarrage", flush=True)
    print(f"[collector] API_URL={API_URL}  BACNET_SNIFF_ENABLE={BACNET_SNIFF_ENABLE}", flush=True)

    ifaces = list_interfaces()
    print(f"[collector] {len(ifaces)} interface(s) IPv4 :", flush=True)
    for i in ifaces:
        print(f"  {i['name']:20} {i['ip']}/{i['prefix']:2}  broadcast={i['broadcast']}", flush=True)
    print("=" * 60, flush=True)

    stop_event = asyncio.Event()
    state: dict = {"sniffer": "init", "worker": "init", "frames": 0, "jobs_done": 0}

    tasks = []
    if BACNET_SNIFF_ENABLE:
        tasks.append(asyncio.create_task(
            supervised("sniffer", lambda: run_sniffer(API_URL, HEADERS, stop_event, state), state),
            name="sniffer",
        ))
    else:
        state["sniffer"] = "disabled"
        print("[collector] sniffer BACnet désactivé (BACNET_SNIFF_ENABLE=0)", flush=True)

    tasks.append(asyncio.create_task(
        supervised("worker", lambda: run_worker(API_URL, HEADERS, stop_event, state), state),
        name="worker",
    ))
    tasks.append(asyncio.create_task(heartbeat(state), name="heartbeat"))

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("[collector] arrêt (KeyboardInterrupt)", flush=True)
