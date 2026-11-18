import psutil
import time
import platform

def get_system_info():
    cpu_usage = psutil.cpu_percent(interval=1)

    memory = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    network = psutil.net_io_counters()
    uptime_seconds = time.time() - psutil.boot_time()
    uptime_hours = round(uptime_seconds / 3600, 2)

    return {
        "cpu": cpu_usage,
        "ram": memory.percent,
        "ram_total": round(memory.total / (1024 ** 3), 2),
        "ram_used": round(memory.used / (1024 ** 3), 2),
        "disk": disk.percent,
        "disk_total": round(disk.total / (1024 ** 3), 2),
        "disk_used": round(disk.used / (1024 ** 3), 2),
        "disk_free": round(disk.free / (1024 ** 3), 2),
        "network_sent": round(network.bytes_sent / (1024 ** 2), 2),
        "network_received": round(network.bytes_recv / (1024 ** 2), 2),
        "uptime": uptime_hours,
        "os": platform.system()
    }



